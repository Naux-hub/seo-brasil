"""
server.py — Nuvemshop proxy wrapper for SEO Brasil

Startar Streamlit som subprocess på port 8501, sedan:
  - Hanterar /auth/nuvemshop   → OAuth-exchange med Nuvemshop
  - Hanterar /webhooks/*       → LGPD-svar (200 OK)
  - Proxar allt annat (inkl. WebSockets) → Streamlit

Startkommando i Railway: python server.py
"""

import asyncio
import os
import subprocess
import sys
import time
import logging

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

STREAMLIT_PORT = 8501
STREAMLIT_BASE = f"http://127.0.0.1:{STREAMLIT_PORT}"
STREAMLIT_WS   = f"ws://127.0.0.1:{STREAMLIT_PORT}"

APP_ID        = os.environ.get("NUVEMSHOP_APP_ID", "45429")
CLIENT_SECRET = os.environ.get("NUVEMSHOP_CLIENT_SECRET", "")
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")

async def store_redact(request: Request) -> Response:
    log.info("LGPD store-redact anropad")
    return Response(status_code=200)

async def customers_redact(request: Request) -> Response:
    log.info("LGPD customers-redact anropad")
    return Response(status_code=200)

async def customers_data_request(request: Request) -> Response:
    log.info("LGPD customers-data-request anropad")
    return JSONResponse({"customer_data": []})

async def nuvemshop_auth(request: Request) -> Response:
    code     = request.query_params.get("code")
    store_id = request.query_params.get("user_id")
    if not code or not store_id:
        return Response("Saknar code eller user_id", status_code=400)
    token_url = f"https://www.nuvemshop.com.br/apps/{APP_ID}/authorize"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(token_url, data={
                "client_id":     APP_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "code":          code,
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"Token-exchange misslyckades: {e}")
            return Response(f"Auth misslyckades: {e}", status_code=500)
    access_token = data.get("access_token")
    if not access_token:
        return Response("Ingen access_token i svar", status_code=500)
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            sb = create_client(SUPABASE_URL, SUPABASE_KEY)
            sb.table("nuvemshop_tokens").upsert({
                "store_id":     str(store_id),
                "access_token": access_token,
                "scope":        data.get("scope", ""),
            }).execute()
            log.info(f"Token sparad för butik {store_id}")
        except Exception as e:
            log.warning(f"Kunde inte spara token: {e}")
    return RedirectResponse(url="/", status_code=302)

_SKIP_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}

async def proxy_http(request: Request) -> Response:
    # Starlette catch-all workaround: dispatcha explicit innan proxy
    if request.url.path == "/auth/nuvemshop":
        return await nuvemshop_auth(request)
    path  = request.url.path
    query = request.url.query
    url   = f"{STREAMLIT_BASE}{path}"
    if query:
        url += f"?{query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_HEADERS}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            body = await request.body()
            resp = await client.request(method=request.method, url=url, headers=headers, content=body, follow_redirects=False)
        except httpx.ConnectError:
            return Response("Streamlit startar, försök igen om ett ögonblick...", status_code=503)
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in {"content-encoding", "transfer-encoding", "connection"}}
    return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)

async def proxy_ws(ws_client: WebSocket) -> None:
    path  = ws_client.url.path
    query = ws_client.url.query
    url   = f"{STREAMLIT_WS}{path}"
    if query:
        url += f"?{query}"
    await ws_client.accept()
    try:
        async with websockets.connect(url) as ws_server:
            async def c2s():
                try:
                    async for msg in ws_client.iter_bytes():
                        await ws_server.send(msg)
                except WebSocketDisconnect:
                    pass
            async def s2c():
                try:
                    async for msg in ws_server:
                        if isinstance(msg, bytes):
                            await ws_client.send_bytes(msg)
                        else:
                            await ws_client.send_text(msg)
                except Exception:
                    pass
            await asyncio.gather(c2s(), s2c())
    except Exception as e:
        log.debug(f"WS proxy avslutad: {e}")

routes = [
    Route("/webhooks/store-redact",           store_redact,           methods=["POST"]),
    Route("/webhooks/customers-redact",       customers_redact,       methods=["POST"]),
    Route("/webhooks/customers-data-request", customers_data_request, methods=["POST"]),
    Route("/auth/nuvemshop",                  nuvemshop_auth,         methods=["GET"]),
    WebSocketRoute("/{path:path}",            proxy_ws),
    Route("/{path:path}",                     proxy_http),
    Route("/",                                proxy_http),
]

app = Starlette(routes=routes)

def start_streamlit():
    env = os.environ.copy()
    env.pop("PORT", None)   # Hindrar Streamlit fran att arva Railwayss PORT och ta 8080
    cmd = [sys.executable, "-m", "streamlit", "run", "app.py",
           "--server.port", str(STREAMLIT_PORT), "--server.headless", "true",
           "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false"]
    log.info(f"Startar Streamlit på port {STREAMLIT_PORT}…")
    return subprocess.Popen(cmd, env=env)

def wait_for_streamlit(timeout=30):
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", STREAMLIT_PORT), timeout=1):
                log.info("Streamlit är redo.")
                return True
        except OSError:
            time.sleep(0.5)
    log.warning("Streamlit svarade inte inom timeout.")
    return False

if __name__ == "__main__":
    _proc = start_streamlit()
    wait_for_streamlit()
    port = int(os.environ.get("PORT", 8000))
    log.info(f"Proxy lyssnar på port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

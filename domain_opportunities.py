"""
domain_opportunities.py
=======================
Isolerad modul för "Oportunidades de Domínios"-funktionen.

Hanterar:
  - CatchDoms API (source=regfree, tld=.com.br)
  - DataForSEO bulk_ranks/live + bulk_spam_score/live (parallel)
  - Merge av resultaten

VIKTIG ISOLERING:
  - Inga importer från övriga SEO Brasil-moduler.
  - Ingen Supabase-skrivning.
  - Inga ändringar av affiliate/outreach/domain_enrichment.
  - Credentials passas alltid in utifrån — exponeras aldrig i output.
"""

import requests
import logging
import concurrent.futures
from typing import Optional

CATCHDOMS_API_URL = "https://catchdoms.com/api/domains"

MAJESTIC_CATEGORIES = [
    "Arts", "Business", "Computers", "Games", "Health", "Home",
    "Kids and Teens", "News", "Recreation", "Reference", "Regional",
    "Science", "Shopping", "Society", "Sports", "World",
]


# ── CATCHDOMS ────────────────────────────────────────────────────────────────

def fetch_catchdoms(
    tf_min: int = 15,
    rd_min: int = 15,
    score_min: int = 45,
    age_min: int = 0,
    categories: Optional[list] = None,
    per_page: int = 25,
    token: str = "",
) -> "list | dict":
    """
    Anropar CatchDoms /api/domains med source=regfree, tld=.com.br.

    Returnerar:
      - Lista med domän-dicts vid framgång (kan vara tom [])
      - Dict {"error": "<kod>", "message": "<sv/pt-meddelande>"} vid fel

    Kastar inga exceptions utåt.
    Credentials exponeras aldrig i retur-värdet.
    """
    if not token:
        return {"error": "no_token", "message": "Token CatchDoms não configurado."}

    params = {
        "source": "regfree",
        "tld": ".com.br",
        "language": "pt",
        "has_backlinks": 1,
        "tf_min": tf_min,
        "rd_min": rd_min,
        "score_min": score_min,
        "per_page": min(per_page, 25),  # MVP-tak
        "page": 1,
    }
    if age_min and age_min > 0:
        params["age_min"] = age_min
    if categories:
        params["categories"] = ",".join(categories)

    try:
        r = requests.get(
            CATCHDOMS_API_URL,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
    except requests.Timeout:
        logging.warning("[catchdoms] timeout")
        return {"error": "timeout", "message": "Serviço temporariamente indisponível (timeout). Tente novamente."}
    except requests.ConnectionError:
        logging.exception("[catchdoms] connection error")
        return {"error": "connection", "message": "Não foi possível conectar ao CatchDoms. Verifique sua conexão."}
    except Exception:
        logging.exception("[catchdoms] fetch error inesperado")
        return {"error": "unknown", "message": "Erro inesperado ao buscar domínios."}

    if r.status_code == 401 or r.status_code == 403:
        return {"error": "auth", "message": "Acesso ao catálogo requer plano Authority+ ativo no CatchDoms."}
    if r.status_code == 429:
        return {"error": "rate_limit", "message": "Limite de requisições atingido. Aguarde alguns segundos e tente novamente."}
    if not r.ok:
        return {"error": "http", "message": f"Erro HTTP {r.status_code} ao buscar domínios."}

    try:
        data = r.json()
    except Exception:
        logging.exception("[catchdoms] JSON parse error")
        return {"error": "parse", "message": "Resposta inválida do CatchDoms."}

    # CatchDoms pode retornar lista direta ou objeto com campo "domains"/"data"
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("domains", "data", "results", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
    # Resposta inesperada mas sem erro explícito — retorna vazio
    logging.warning("[catchdoms] resposta inesperada: %s", str(data)[:200])
    return []


# ── DATAFORSEO BULK ENRICHMENT ────────────────────────────────────────────────

def _fetch_bulk_ranks(
    targets: list,
    login: str,
    password: str,
) -> dict:
    """
    POST /v3/backlinks/bulk_ranks/live.
    Retorna {domain: rank_ou_None}.
    rank=0 é preservado (domínio existe mas sem backlinks no índice).
    rank=None significa que domínio não foi encontrado ou erro.
    """
    result = {t: None for t in targets}
    if not targets:
        return result
    try:
        r = requests.post(
            "https://api.dataforseo.com/v3/backlinks/bulk_ranks/live",
            auth=(login, password),
            json=[{"targets": targets, "rank_scale": "one_hundred"}],
            timeout=20,
        )
        data = r.json()
        if data.get("status_code") == 20000:
            task = (data.get("tasks") or [{}])[0]
            if task.get("status_code") == 20000:
                items = []
                for block in (task.get("result") or []):
                    items.extend(block.get("items") or [])
                for item in items:
                    t = item.get("target")
                    if t in result:
                        # rank=0 är giltigt — skiljs från None
                        rank_val = item.get("rank")
                        result[t] = rank_val  # None om saknas, 0 om indexerat men noll
    except Exception:
        logging.exception("[domain_opps] bulk_ranks error")
    return result


def _fetch_bulk_spam_score(
    targets: list,
    login: str,
    password: str,
) -> dict:
    """
    POST /v3/backlinks/bulk_spam_score/live.
    Retorna {domain: spam_score_ou_None}.
    None bevaras om domänen saknas i svaret — ej 0.
    """
    result = {t: None for t in targets}
    if not targets:
        return result
    try:
        r = requests.post(
            "https://api.dataforseo.com/v3/backlinks/bulk_spam_score/live",
            auth=(login, password),
            json=[{"targets": targets}],
            timeout=20,
        )
        data = r.json()
        if data.get("status_code") == 20000:
            task = (data.get("tasks") or [{}])[0]
            if task.get("status_code") == 20000:
                items = []
                for block in (task.get("result") or []):
                    items.extend(block.get("items") or [])
                for item in items:
                    t = item.get("target")
                    if t in result:
                        result[t] = item.get("spam_score")  # None bevaras
    except Exception:
        logging.exception("[domain_opps] bulk_spam_score error")
    return result


def enrich_with_dataforseo(
    domains: list,
    login: str,
    password: str,
) -> dict:
    """
    Kör bulk_ranks och bulk_spam_score parallellt.
    Retorna {domain: {"dr": int|None, "ss": int|None}}.

    dr=0 är giltigt (skiljs från None).
    ss=None bevaras om domänen inte hittades.
    """
    if not domains:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_ranks = executor.submit(_fetch_bulk_ranks, domains, login, password)
        future_ss = executor.submit(_fetch_bulk_spam_score, domains, login, password)
        ranks = future_ranks.result()
        spam_scores = future_ss.result()
    return {
        d: {"dr": ranks.get(d), "ss": spam_scores.get(d)}
        for d in domains
    }


# ── MERGE ─────────────────────────────────────────────────────────────────────

def merge_results(
    catchdoms_list: list,
    dataforseo_map: dict,
) -> list:
    """
    Lägger till "dr" och "ss" från dataforseo_map till varje CatchDoms-post.
    Originaldatan från CatchDoms bevaras oförändrad.
    """
    merged = []
    for d in catchdoms_list:
        name = d.get("name", "")
        enriched = dataforseo_map.get(name, {})
        merged.append({
            **d,
            "dr": enriched.get("dr"),   # None om ej berikad
            "ss": enriched.get("ss"),   # None om ej berikad
        })
    return merged


# ── FORMATTING HELPERS ─────────────────────────────────────────────────────────

def compact_num(n) -> str:
    """Formaterar tal kompakt: 1234 → '1.2k', 1234567 → '1.2M'. None → '—'."""
    if n is None:
        return "—"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def tf_cf_ratio(tf, cf) -> Optional[str]:
    """
    Beräknar TF/CF-ratio som procentsträng.
    Returnerar None om CF=0 eller något värde saknas.
    """
    if tf is None or cf is None or cf == 0:
        return None
    return f"{round(tf / cf * 100)}%"


def registro_br_url(domain_name: str) -> str:
    """Returnerar Registro.br söknings-URL för given domän."""
    return f"https://registro.br/pesquisa-dominio/?domain={domain_name}"


def wayback_url(domain_name: str) -> str:
    """Returnerar Wayback Machine URL för given domän."""
    return f"https://web.archive.org/web/*/{domain_name}"


def majestic_url(domain_name: str) -> str:
    """Returnerar Majestic Site Explorer URL."""
    return f"https://majestic.com/reports/site-explorer?q={domain_name}"

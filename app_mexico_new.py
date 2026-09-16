import os
import streamlit as st
import pandas as pd
import requests
import time
from supabase import create_client
from keyword_cache import get_keyword_data, get_keyword_ideas
from datetime import datetime, timedelta, timezone
from streamlit_cookies_controller import CookieController
import streamlit.components.v1 as components
from urllib.parse import quote as urlquote
from market_config import get_market

# ── MERCADO: México ───────────────────────────────────────────────────────────
MARKET = "mx"
_cfg = get_market(MARKET)
LOCATION_CODE = _cfg["location_code"]   # 2484
LANGUAGE_CODE = _cfg["language_code"]   # "es"
PRODUCT_NAME  = _cfg["product_name"]    # "SEO México"
PRODUCT_URL   = _cfg["product_url"]     # "https://seomexico.app"

# ── CREDENCIALES ──────────────────────────────────────────────────────────────
DATAFORSEO_LOGIN    = os.environ["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = os.environ["DATAFORSEO_PASSWORD"]
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

HOTMART_URL    = os.environ.get("HOTMART_MX_URL", "")   # se configura al lanzar
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 días en segundos

cookie = CookieController()


# ── HELPERS SUPABASE ──────────────────────────────────────────────────────────

def es_suscriptor(email):
    res = supabase.table("subscribers").select("email").eq("email", email).eq("market", MARKET).execute()
    return len(res.data) > 0


def get_tracked_set(user_id):
    res = (
        supabase.table("tracked_keywords")
        .select("keyword")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .eq("market", MARKET)
        .execute()
    )
    return {r["keyword"] for r in res.data}


def add_tracking(keyword, user_id):
    count_res = (
        supabase.table("tracked_keywords")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .eq("market", MARKET)
        .execute()
    )
    if len(count_res.data) >= 20:
        return False, "Límite de 20 palabras alcanzado."
    try:
        existing = (
            supabase.table("tracked_keywords")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("keyword", keyword)
            .eq("market", MARKET)
            .execute()
        )
        if existing.data:
            supabase.table("tracked_keywords").update({"is_active": True}).eq("user_id", str(user_id)).eq("keyword", keyword).eq("market", MARKET).execute()
        else:
            supabase.table("tracked_keywords").insert({
                "user_id": str(user_id),
                "keyword": keyword,
                "is_active": True,
                "market": MARKET,
            }).execute()
        return True, "ok"
    except Exception as e:
        return False, f"Error: {str(e)}"


def remove_tracking(keyword, user_id):
    supabase.table("tracked_keywords").update({"is_active": False}).eq("user_id", str(user_id)).eq("keyword", keyword).eq("market", MARKET).execute()


def get_tracked_keywords_list(user_id):
    res = (
        supabase.table("tracked_keywords")
        .select("keyword, created_at")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .eq("market", MARKET)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


@st.cache_data(ttl=3600)
def get_social_proof():
    """Obtiene cifras en vivo para prueba social. Cacheado 1 hora."""
    try:
        total_kw = supabase.table("keyword_cache").select("keyword", count="exact").execute()
        kw_count = total_kw.count or 0
        kw_display = (kw_count // 100) * 100
        return kw_display
    except Exception:
        return 2000


def get_user_domain(email):
    res = supabase.table("subscribers").select("domain").eq("email", email).execute()
    if res.data and res.data[0].get("domain"):
        return res.data[0]["domain"]
    return None


def get_trial_status(email):
    res = supabase.table("subscribers").select("subscription_status, created_at").eq("email", email).execute()
    if not res.data:
        return "NO_SUBSCRIBER"
    row = res.data[0]
    if row.get("subscription_status") == "active":
        return "ACTIVE"
    created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - created_at).days
    if days <= 14:
        return "TRIAL_ACTIVE"
    return "TRIAL_EXPIRED"


def create_trial_account(email, contrasena):
    """
    Crea una cuenta (Supabase Auth) + fila en subscribers con subscription_status='trial'
    y hace login automático.

    Retorna (exito: bool, error: str | None). error == "DUPLICATE" si el email ya existe.
    """
    try:
        import requests as _req
        _svc_key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
        _adm_resp = _req.post(
            f"{os.environ['SUPABASE_URL']}/auth/v1/admin/users",
            headers={
                "apikey": _svc_key,
                "Authorization": f"Bearer {_svc_key}",
                "Content-Type": "application/json",
            },
            json={"email": email, "password": contrasena, "email_confirm": True},
        )
        if not _adm_resp.ok:
            raise Exception(_adm_resp.json().get("msg", _adm_resp.text))
        _uid = _adm_resp.json()["id"]

        try:
            supabase.table("subscribers").insert({
                "email": email,
                "user_id": _uid,
                "subscription_status": "trial",
                "market": MARKET,
            }).execute()
        except Exception as _sub_err:
            print(f"[create_trial_account] subscribers.insert falló para {email}: {_sub_err}")
            try:
                _req.delete(
                    f"{os.environ['SUPABASE_URL']}/auth/v1/admin/users/{_uid}",
                    headers={"apikey": _svc_key, "Authorization": f"Bearer {_svc_key}"},
                )
            except Exception as _del_err:
                print(f"[create_trial_account] AVISO: No se pudo eliminar cuenta auth {_uid}: {_del_err}")
            raise Exception(f"Error al guardar cuenta: {_sub_err}")

        _login = supabase.auth.sign_in_with_password({"email": email, "password": contrasena})
        st.session_state.user = _login.user
        st.session_state.access_token = _login.session.access_token
        st.session_state.refresh_token = _login.session.refresh_token
        supabase.postgrest.auth(_login.session.access_token)
        try:
            cookie.set("sb_access_token", _login.session.access_token, max_age=COOKIE_MAX_AGE)
            cookie.set("sb_refresh_token", _login.session.refresh_token, max_age=COOKIE_MAX_AGE)
        except Exception:
            pass
        return True, None
    except Exception as e:
        _err_str = str(e).lower()
        if any(x in _err_str for x in ("already", "duplicate")):
            return False, "DUPLICATE"
        return False, str(e)


def save_user_domain(email, domain):
    domain = domain.strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    supabase.table("subscribers").update({"domain": domain}).eq("email", email).execute()


def get_rank_data_for_keyword(user_id, keyword, domain):
    if not domain:
        return None
    res = (
        supabase.table("keyword_rankings")
        .select("rank_position, prev_rank_position, checked_at")
        .eq("user_id", str(user_id))
        .eq("keyword", keyword)
        .eq("domain", domain)
        .eq("market", MARKET)
        .order("checked_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def trend_label(row):
    if not row:
        return "⏳ Esperando datos"
    current = row.get("rank_position")
    prev = row.get("prev_rank_position")
    if current is None:
        return "📉 Fuera del top 100" if prev else "🔍 No encontrado en top 100"
    if prev is None:
        return f"#{current} 🆕 Nuevo"
    diff = prev - current
    if diff > 0:
        return f"#{current} 📈 +{diff} posiciones"
    elif diff < 0:
        return f"#{current} 📉 {abs(diff)} posiciones"
    else:
        return f"#{current} → Estable"


# ── SEGUIMIENTO DE ACTIVACIÓN ─────────────────────────────────────────────────

def log_event(user_id, event, metadata=None):
    """Registra un evento de activación. Nunca bloquea el app."""
    try:
        supabase.table("user_events").insert({
            "user_id": str(user_id),
            "event": event,
            "metadata": metadata or {},
        }).execute()
    except Exception:
        pass


def has_any_rankings(user_id):
    """Verifica si el usuario ya tiene datos de ranking."""
    try:
        res = (
            supabase.table("keyword_rankings")
            .select("user_id", count="exact")
            .eq("user_id", str(user_id))
            .eq("market", MARKET)
            .limit(1)
            .execute()
        )
        return (res.count or 0) > 0
    except Exception:
        return False


# ── RANKING ON-DEMAND ─────────────────────────────────────────────────────────

def _fetch_single_rank(keyword, domain, login, password):
    """
    Busca posición de una keyword en Google México via DataForSEO.
    Retorna (position, url) o (None, None) en caso de error.
    """
    tasks = [{
        "keyword": keyword,
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
        "depth": 100,
    }]
    try:
        r = requests.post(
            "https://api.dataforseo.com/v3/serp/google/organic/task_post",
            auth=(login, password), json=tasks, timeout=30,
        )
        data = r.json()
    except Exception:
        return None, None

    if data.get("status_code") != 20000:
        return None, None

    task_items = data.get("tasks", [])
    if not task_items:
        return None, None
    task_id = task_items[0].get("id")
    if not task_id:
        return None, None

    for wait_time in [15, 5, 5]:
        time.sleep(wait_time)
        try:
            r = requests.get(
                f"https://api.dataforseo.com/v3/serp/google/organic/task_get/regular/{task_id}",
                auth=(login, password), timeout=30,
            )
            result_data = r.json()
            tasks_list = result_data.get("tasks", [])
            if not tasks_list:
                continue
            result = tasks_list[0].get("result") or []
            if not result:
                continue
            items = result[0].get("items", [])
            if not items:
                continue
            for item in items:
                if item.get("type") != "organic":
                    continue
                item_url = item.get("url", "") or ""
                item_domain = item.get("domain", "") or ""
                if domain in item_url or domain in item_domain:
                    return item.get("rank_absolute"), item_url
            return None, None
        except Exception:
            continue

    return None, None


def run_on_demand_ranking(user_id, domain, keywords, login, password,
                          status_el, progress_bar):
    """
    Verifica posición en Google México para todos los keywords con feedback visual.
    Guarda en keyword_rankings y retorna dict de resultados.
    """
    results = {}
    total = len(keywords)

    for i, kw in enumerate(keywords):
        status_el.markdown(
            f"<span style='color:#9CA3AF;font-size:0.9rem'>"
            f"Verificando {i + 1} de {total}: <em>{kw}</em>...</span>",
            unsafe_allow_html=True,
        )
        progress_bar.progress(i / total)
        position, url = _fetch_single_rank(kw, domain, login, password)
        results[kw] = {"position": position, "url": url}

    progress_bar.progress(1.0)
    status_el.empty()

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": str(user_id),
            "keyword": kw,
            "domain": domain,
            "rank_position": d["position"],
            "prev_rank_position": None,
            "checked_at": now,
            "market": MARKET,
        }
        for kw, d in results.items()
    ]
    if rows:
        supabase.table("keyword_rankings").upsert(
            rows, on_conflict="user_id,keyword,domain"
        ).execute()

    return results


# ── UI PRINCIPAL ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SEO México",
    page_icon="🇲🇽",
    layout="centered",
)

# ── CSS BASE (mismo que Brasil, neutro) ───────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #0f0f0f; }
  [data-testid="stMainBlockContainer"] { max-width: 820px; padding: 2rem 1rem; }
  h1, h2, h3 { color: #f0f0f0; }
  p, li, span { color: #d1d5db; }
  .stTextInput input, .stTextArea textarea {
    background: #1a1a1a; border: 1px solid #333; color: #f0f0f0;
  }
  .stButton button {
    background: #16a34a; color: white; border: none;
    border-radius: 6px; padding: 0.5rem 1.5rem;
  }
  .stButton button:hover { background: #15803d; }
</style>
""", unsafe_allow_html=True)


# ── GESTIÓN DE SESIÓN (idéntica a Brasil) ─────────────────────────────────────

if "user" not in st.session_state:
    st.session_state.user = None
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

# Intentar restaurar sesión desde cookies
if st.session_state.user is None:
    try:
        _at = cookie.get("sb_access_token")
        _rt = cookie.get("sb_refresh_token")
        if _at and _rt:
            _session = supabase.auth.set_session(_at, _rt)
            if _session and _session.user:
                st.session_state.user = _session.user
                st.session_state.access_token = _at
                st.session_state.refresh_token = _rt
                supabase.postgrest.auth(_at)
    except Exception:
        pass


# ── ENRUTAMIENTO ──────────────────────────────────────────────────────────────

user = st.session_state.user
logged_in = user is not None

if not logged_in:
    _show_landing()
else:
    email = user.email
    status = get_trial_status(email)
    if status == "TRIAL_EXPIRED":
        _show_upgrade_wall()
    elif status in ("TRIAL_ACTIVE", "ACTIVE"):
        _show_dashboard(email, user, status)
    else:
        _show_landing()


# ── LANDING PAGE ──────────────────────────────────────────────────────────────

def _show_landing():
    st.markdown("""
    <div style='text-align:center; padding: 3rem 0 1rem'>
      <h1 style='font-size:2.8rem; font-weight:800; color:#f0f0f0'>
        SEO México 🇲🇽
      </h1>
      <p style='font-size:1.2rem; color:#9ca3af; max-width:520px; margin:0 auto 2rem'>
        Encuentra las palabras clave que usan tus clientes en México —
        y ve exactamente dónde aparece tu sitio en Google.
      </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Crear cuenta gratis")
        with st.form("registro_form"):
            new_email = st.text_input("Correo electrónico")
            new_pass  = st.text_input("Contraseña (mín. 6 caracteres)", type="password")
            submitted = st.form_submit_button("Empezar prueba gratuita — 14 días")
            if submitted:
                if not new_email or not new_pass:
                    st.error("Completa todos los campos.")
                elif len(new_pass) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    ok, err = create_trial_account(new_email, new_pass)
                    if ok:
                        st.success("¡Cuenta creada! Bienvenido a SEO México.")
                        st.rerun()
                    elif err == "DUPLICATE":
                        st.warning("Este correo ya tiene cuenta. Inicia sesión abajo.")
                    else:
                        st.error(f"Error: {err}")

    with col2:
        st.markdown("### Ya tengo cuenta")
        with st.form("login_form"):
            login_email = st.text_input("Correo electrónico", key="l_email")
            login_pass  = st.text_input("Contraseña", type="password", key="l_pass")
            login_btn   = st.form_submit_button("Iniciar sesión")
            if login_btn:
                try:
                    session = supabase.auth.sign_in_with_password({
                        "email": login_email,
                        "password": login_pass,
                    })
                    st.session_state.user = session.user
                    st.session_state.access_token = session.session.access_token
                    st.session_state.refresh_token = session.session.refresh_token
                    supabase.postgrest.auth(session.session.access_token)
                    try:
                        cookie.set("sb_access_token", session.session.access_token, max_age=COOKIE_MAX_AGE)
                        cookie.set("sb_refresh_token", session.session.refresh_token, max_age=COOKIE_MAX_AGE)
                    except Exception:
                        pass
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al iniciar sesión: {str(e)}")

    st.divider()
    _show_features()


def _show_features():
    st.markdown("## ¿Qué incluye SEO México?")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 🔍 Palabras clave")
        st.markdown("Descubre qué buscan tus clientes en Google México con volumen de búsqueda real.")
    with col2:
        st.markdown("### 📊 Rastreo de posiciones")
        st.markdown("Monitorea dónde aparece tu sitio en Google para tus palabras clave más importantes.")
    with col3:
        st.markdown("### 📈 Tendencias")
        st.markdown("Ve si estás subiendo o bajando en los resultados semana a semana.")


# ── MURO DE UPGRADE ───────────────────────────────────────────────────────────

def _show_upgrade_wall():
    st.markdown("""
    <div style='text-align:center; padding: 3rem 0'>
      <h2 style='color:#f0f0f0'>Tu prueba gratuita ha terminado</h2>
      <p style='color:#9ca3af; font-size:1.1rem'>
        Actualiza a SEO México para seguir viendo tus palabras clave y posiciones.
      </p>
    </div>
    """, unsafe_allow_html=True)

    if HOTMART_URL:
        st.markdown(
            f"<div style='text-align:center'>"
            f"<a href='{HOTMART_URL}' target='_blank' style='"
            f"background:#16a34a;color:white;padding:0.75rem 2rem;"
            f"border-radius:8px;text-decoration:none;font-size:1.1rem;font-weight:600'>"
            f"Suscribirme ahora</a></div>",
            unsafe_allow_html=True,
        )
    else:
        st.info("La suscripción estará disponible pronto. ¡Gracias por tu paciencia!")

    if st.button("Cerrar sesión"):
        _logout()


# ── DASHBOARD PRINCIPAL ───────────────────────────────────────────────────────

def _show_dashboard(email, user, status):
    user_id = user.id
    domain  = get_user_domain(email)

    # Sidebar
    with st.sidebar:
        st.markdown(f"**{email}**")
        st.caption("SEO México 🇲🇽")
        if status == "TRIAL_ACTIVE":
            sub_res = supabase.table("subscribers").select("created_at").eq("email", email).execute()
            if sub_res.data:
                created = datetime.fromisoformat(sub_res.data[0]["created_at"].replace("Z", "+00:00"))
                days_left = 14 - (datetime.now(timezone.utc) - created).days
                st.info(f"Prueba: {max(0, days_left)} días restantes")
        if st.button("Cerrar sesión"):
            _logout()

    tab1, tab2, tab3 = st.tabs(["🔍 Palabras clave", "📊 Mis posiciones", "⚙️ Mi sitio"])

    # ── Tab 1: Investigación de palabras clave ────────────────────────────────
    with tab1:
        st.header("Investigación de palabras clave")
        st.caption("Datos de Google México — volúmenes de búsqueda mensuales")

        with st.form("keyword_form"):
            keyword_input = st.text_input(
                "Ingresa una palabra clave",
                placeholder="ej. agencia de marketing digital"
            )
            buscar = st.form_submit_button("Buscar")

        if buscar and keyword_input.strip():
            kw = keyword_input.strip()
            with st.spinner("Buscando palabras clave..."):
                try:
                    ideas = get_keyword_ideas(
                        [kw], supabase,
                        DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
                    )
                    if ideas:
                        df = pd.DataFrame(ideas)
                        if "search_volume" in df.columns:
                            df = df.sort_values("search_volume", ascending=False)
                        st.dataframe(df, use_container_width=True)

                        tracked = get_tracked_set(user_id)
                        st.subheader("Agregar al rastreo")
                        for _, row in df.head(10).iterrows():
                            kw_item = row.get("keyword", "")
                            vol = row.get("search_volume", "—")
                            col_kw, col_vol, col_btn = st.columns([3, 1, 1])
                            col_kw.write(kw_item)
                            col_vol.write(f"{vol:,}" if isinstance(vol, (int, float)) else "—")
                            if kw_item in tracked:
                                col_btn.write("✅ Rastreando")
                            else:
                                if col_btn.button("+ Agregar", key=f"add_{kw_item}"):
                                    ok, msg = add_tracking(kw_item, user_id)
                                    if ok:
                                        log_event(user_id, "keyword_tracked", {"keyword": kw_item})
                                        st.rerun()
                                    else:
                                        st.warning(msg)
                    else:
                        st.info("No se encontraron palabras clave relacionadas.")
                except Exception as e:
                    st.error(f"Error al buscar: {str(e)}")

    # ── Tab 2: Posiciones ─────────────────────────────────────────────────────
    with tab2:
        st.header("Mis posiciones en Google México")

        if not domain:
            st.info("Configura tu dominio en la pestaña **⚙️ Mi sitio** para ver tus posiciones.")
        else:
            tracked_kws = get_tracked_keywords_list(user_id)
            if not tracked_kws:
                st.info("Aún no tienes palabras clave rastreadas. Ve a **🔍 Palabras clave** para agregar algunas.")
            else:
                keywords_list = [r["keyword"] for r in tracked_kws]

                col_update, col_info = st.columns([1, 3])
                with col_update:
                    if st.button("🔄 Actualizar posiciones ahora"):
                        status_el   = st.empty()
                        progress_bar = st.progress(0)
                        results = run_on_demand_ranking(
                            user_id, domain, keywords_list,
                            DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
                            status_el, progress_bar,
                        )
                        log_event(user_id, "manual_rank_check", {"keyword_count": len(keywords_list)})
                        st.rerun()
                with col_info:
                    st.caption("Las posiciones también se actualizan automáticamente cada lunes.")

                # Mostrar tabla de rankings
                rows = []
                for kw_item in keywords_list:
                    rank_data = get_rank_data_for_keyword(user_id, kw_item, domain)
                    trend = trend_label(rank_data)
                    checked = "—"
                    if rank_data and rank_data.get("checked_at"):
                        try:
                            dt = datetime.fromisoformat(rank_data["checked_at"].replace("Z", "+00:00"))
                            checked = dt.strftime("%d/%m/%Y")
                        except Exception:
                            pass
                    rows.append({
                        "Palabra clave": kw_item,
                        "Posición": trend,
                        "Actualizado": checked,
                    })

                if rows:
                    df = pd.DataFrame(rows)
                    st.dataframe(df, use_container_width=True, hide_index=True)

                # Gestión de palabras clave rastreadas
                with st.expander("Gestionar palabras clave rastreadas"):
                    for kw_item in keywords_list:
                        col_name, col_del = st.columns([4, 1])
                        col_name.write(kw_item)
                        if col_del.button("🗑️", key=f"del_{kw_item}"):
                            remove_tracking(kw_item, user_id)
                            st.rerun()

    # ── Tab 3: Configuración del sitio ────────────────────────────────────────
    with tab3:
        st.header("Mi sitio")

        if domain:
            st.success(f"Sitio configurado: **{domain}**")
        else:
            st.info("Ingresa tu dominio para empezar a rastrear posiciones.")

        with st.form("domain_form"):
            new_domain = st.text_input(
                "Tu dominio",
                value=domain or "",
                placeholder="ej. miempresa.com.mx"
            )
            save_domain = st.form_submit_button("Guardar")
            if save_domain and new_domain.strip():
                save_user_domain(email, new_domain.strip())
                log_event(user_id, "domain_saved", {"domain": new_domain.strip()})
                st.success("¡Dominio guardado!")
                st.rerun()


# ── LOGOUT ────────────────────────────────────────────────────────────────────

def _logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    try:
        cookie.remove("sb_access_token")
        cookie.remove("sb_refresh_token")
    except Exception:
        pass
    st.session_state.user = None
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.rerun()

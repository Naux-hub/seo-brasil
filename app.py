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

DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = st.secrets["DATAFORSEO_PASSWORD"]
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

HOTMART_URL = "https://pay.hotmart.com/L106736067M"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 dagar i sekunder

cookie = CookieController()

def ar_prenumerant(email):
    res = supabase.table("subscribers").select("email").eq("email", email).execute()
    return len(res.data) > 0

def get_tracked_set(user_id):
    res = supabase.table("tracked_keywords").select("keyword").eq("user_id", str(user_id)).eq("is_active", True).execute()
    return {r["keyword"] for r in res.data}

def add_tracking(keyword, user_id):
    count_res = supabase.table("tracked_keywords").select("id").eq("user_id", str(user_id)).eq("is_active", True).execute()
    if len(count_res.data) >= 20:
        return False, "Limite de 20 palavras atingido."
    try:
        existing = supabase.table("tracked_keywords").select("id").eq("user_id", str(user_id)).eq("keyword", keyword).execute()
        if existing.data:
            supabase.table("tracked_keywords").update({"is_active": True}).eq("user_id", str(user_id)).eq("keyword", keyword).execute()
        else:
            supabase.table("tracked_keywords").insert({
                "user_id": str(user_id),
                "keyword": keyword,
                "is_active": True
            }).execute()
        return True, "ok"
    except Exception as e:
        return False, f"Erro: {str(e)}"

def remove_tracking(keyword, user_id):
    supabase.table("tracked_keywords").update({"is_active": False}).eq("user_id", str(user_id)).eq("keyword", keyword).execute()

def get_tracked_keywords_list(user_id):
    res = supabase.table("tracked_keywords").select("keyword, created_at").eq("user_id", str(user_id)).eq("is_active", True).order("created_at", desc=True).execute()
    return res.data

@st.cache_data(ttl=3600)
def get_social_proof():
    """Hämtar live-siffror för social proof. Cachas i 1 timme."""
    try:
        total_kw = supabase.table("keyword_cache").select("keyword", count="exact").execute()
        kw_count = total_kw.count or 0
        # Avrunda nedåt till närmaste 100 för att undvika att visa exakt antal
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

def create_trial_account(email, senha):
    """
    Cria uma conta (Supabase Auth) + linha em subscribers com subscription_status='trial',
    e faz login automático. Usada tanto pelo fluxo de convite (invite_token) quanto pelo
    formulário público de teste grátis na landing page.

    Retorna (sucesso: bool, erro: str | None). erro == "DUPLICATE" quando o e-mail já existe.
    """
    try:
        import requests as _req
        _adm_resp = _req.post(
            f"{st.secrets['SUPABASE_URL']}/auth/v1/admin/users",
            headers={
                "apikey": st.secrets["SUPABASE_KEY"],
                "Authorization": f"Bearer {st.secrets['SUPABASE_KEY']}",
                "Content-Type": "application/json",
            },
            json={"email": email, "password": senha, "email_confirm": True},
        )
        if not _adm_resp.ok:
            raise Exception(_adm_resp.json().get("msg", _adm_resp.text))
        _uid = _adm_resp.json()["id"]

        try:
            supabase.table("subscribers").insert({
                "email": email,
                "user_id": _uid,
                "subscription_status": "trial",
            }).execute()
        except Exception:
            pass

        _login = supabase.auth.sign_in_with_password({"email": email, "password": senha})
        st.session_state.user = _login.user
        st.session_state.access_token = _login.session.access_token
        st.session_state.refresh_token = _login.session.refresh_token
        supabase.postgrest.auth(_login.session.access_token)
        try:
            cookie.set("sb_access_token", _login.session.access_token, max_age=COOKIE_MAX_AGE)
            cookie.set("sb_refresh_token", _login.session.refresh_token, max_age=COOKIE_MAX_AGE)
        except Exception:
            pass
        _acq = {k: v for k, v in st.session_state.get("acquisition", {}).items() if v}
        log_event(_uid, "signup_completed", _acq if _acq else None)
        return True, None
    except Exception as e:
        _err_str = str(e).lower()
        if any(x in _err_str for x in ("already", "duplicate")):
            return False, "DUPLICATE"
        return False, str(e)

def save_user_domain(email, domain):
    domain = domain.strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    supabase.table("subscribers").update({"domain": domain}).eq("email", email).execute()



def has_event(user_id, event):
    """Returns True if this event has already been logged for this user. Silent on error."""
    try:
        res = supabase.table("user_events").select("id").eq("user_id", str(user_id)).eq("event", event).limit(1).execute()
        return bool(res.data)
    except Exception:
        return False


def get_rank_data_for_keyword(user_id, keyword, domain):
    if not domain:
        return None
    res = supabase.table("keyword_rankings") \
        .select("rank_position, prev_rank_position, checked_at") \
        .eq("user_id", str(user_id)) \
        .eq("keyword", keyword) \
        .eq("domain", domain) \
        .order("checked_at", desc=True) \
        .limit(1) \
        .execute()
    return res.data[0] if res.data else None

def trend_label(row):
    if not row:
        return "⏳ Aguardando dados"
    current = row.get("rank_position")
    prev = row.get("prev_rank_position")
    if current is None:
        return "📉 Saiu do top 100" if prev else "🔍 Não encontrado no top 100"
    if prev is None:
        return f"#{current} 🆕 Novo"
    diff = prev - current  # positivt = klättrade
    if diff > 0:
        return f"#{current} 📈 +{diff} posições"
    elif diff < 0:
        return f"#{current} 📉 {abs(diff)} posições"
    else:
        return f"#{current} → Estável"

# ── ACTIVATION TRACKING ──────────────────────────────────────────────────────

def log_event(user_id, event, metadata=None):
    """Registra um evento de ativação. Nunca trava o app."""
    try:
        supabase.table("user_events").insert({
            "user_id": str(user_id),
            "event": event,
            "metadata": metadata or {},
        }).execute()
    except Exception:
        pass

def has_any_rankings(user_id):
    """Verifica se o usuário já tem dados de ranking."""
    try:
        res = supabase.table("keyword_rankings") \
            .select("user_id", count="exact") \
            .eq("user_id", str(user_id)) \
            .limit(1).execute()
        return (res.count or 0) > 0
    except Exception:
        return False

# ── ON-DEMAND RANKING ─────────────────────────────────────────────────────────

def _fetch_single_rank(keyword, domain, login, password):
    """
    Busca posição de um keyword no Google via DataForSEO (async + retry).
    Retorna (position, url) ou (None, None) em caso de erro.
    """
    tasks = [{"keyword": keyword, "location_code": 2076, "language_code": "pt", "depth": 100}]
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

    # Retry: 15s → 5s → 5s
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
            return None, None  # Não está no top 100
        except Exception:
            continue

    return None, None


def run_on_demand_ranking(user_id, domain, keywords, login, password,
                          status_el, progress_bar):
    """
    Verifica posição no Google para todos os keywords com feedback visual.
    Salva em keyword_rankings e retorna dict de resultados.
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

    # Salvar no Supabase
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": str(user_id),
            "keyword": kw,
            "domain": domain,
            "rank_position": d["position"],
            "prev_rank_position": None,
            "checked_at": now,
        }
        for kw, d in results.items()
    ]
    if rows:
        try:
            supabase.table("keyword_rankings").upsert(
                rows, on_conflict="user_id,keyword,domain"
            ).execute()
        except Exception:
            pass

    return results


# ── IN-APP ONBOARDING ────────────────────────────────────────────────────────

def get_user_events(user_id, event_names):
    """Retorna conjunto de eventos que já ocorreram para este usuário."""
    try:
        res = supabase.table("user_events") \
            .select("event") \
            .eq("user_id", str(user_id)) \
            .in_("event", list(event_names)) \
            .execute()
        return {r["event"] for r in (res.data or [])}
    except Exception:
        return set()


def get_onboarding_status(user_id, domain, ranking_in_progress=False):
    """Calcula o status dos 3 passos de onboarding."""
    step1 = bool(domain)
    step2 = False
    step3 = False
    ranking_completed_not_viewed = False

    if step1:
        try:
            res = supabase.table("tracked_keywords") \
                .select("id", count="exact") \
                .eq("user_id", str(user_id)) \
                .eq("is_active", True) \
                .limit(1).execute()
            step2 = (res.count or 0) > 0
        except Exception:
            step2 = False

    if step2:
        events = get_user_events(
            user_id, ["initial_ranking_completed", "ranking_viewed"]
        )
        has_completed = "initial_ranking_completed" in events
        has_viewed = "ranking_viewed" in events
        has_ranks = has_any_rankings(user_id)
        step3 = has_completed and has_ranks and has_viewed
        ranking_completed_not_viewed = has_completed and has_ranks and not has_viewed

    return {
        "step1": step1,
        "step2": step2,
        "step3": step3,
        "ranking_running": ranking_in_progress,
        "ranking_completed_not_viewed": ranking_completed_not_viewed,
    }


def render_onboarding_progress(status):
    """Renderiza a barra de progresso de onboarding (some quando tudo está completo)."""
    s = status

    # Tudo pronto → não mostrar nada
    if s["step1"] and s["step2"] and s["step3"]:
        return

    def _step_html(label, done, is_next, is_running=False):
        if done:
            bg, border, icon, color, weight = "#0d2b1a", "#2ecc71", "✓", "#2ecc71", "500"
        elif is_running:
            bg, border, icon, color, weight = "rgba(245,158,11,0.1)", "#f59e0b", "⏳", "#f59e0b", "600"
        elif is_next:
            bg, border, icon, color, weight = "rgba(26,109,224,0.12)", "#1a6de0", "→", "#4d9fff", "600"
        else:
            bg, border, icon, color, weight = "#1a1a1a", "#374151", "○", "#6B7280", "400"
        return (
            f"<div style='flex:1;text-align:center;padding:6px 10px;border-radius:6px;"
            f"background:{bg};border:1px solid {border}'>"
            f"<span style='color:{color};font-size:12px;font-weight:{weight}'>"
            f"{icon} {label}</span></div>"
        )

    is_s1_next = not s["step1"]
    is_s2_next = s["step1"] and not s["step2"]
    is_s3_running = s["step2"] and s["ranking_running"]
    is_s3_next = s["step2"] and not s["step3"] and not s["ranking_running"]

    s1_html = _step_html("Adicione seu site",           s["step1"], is_s1_next)
    s2_html = _step_html("Escolha suas palavras-chave", s["step2"], is_s2_next)
    s3_html = _step_html("Veja sua posição no Google",  s["step3"], is_s3_next, is_s3_running)

    if is_s1_next:
        hint = "Próximo: Vá até <b>Meu Monitoramento</b> e adicione o endereço do seu site."
    elif is_s2_next:
        hint = "Próximo: Pesquise uma palavra-chave acima e clique em <b>+ Rastrear</b>."
    elif is_s3_running:
        hint = "Estamos verificando suas posições no Google..."
    elif s["ranking_completed_not_viewed"]:
        hint = "Próximo: Clique em <b>Meu Monitoramento</b> para ver seu ranking."
    elif is_s3_next:
        hint = "Próximo: Pesquise uma palavra-chave e clique em <b>+ Rastrear</b> para verificar sua posição."
    else:
        hint = ""

    st.markdown(f"""
    <div style="background:#111827;border:1px solid #1f2937;border-radius:10px;
                padding:0.75rem 1rem;margin-bottom:0.75rem">
        <div style="font-size:0.72rem;color:#6B7280;margin-bottom:0.55rem;
                    font-weight:600;letter-spacing:0.06em;text-transform:uppercase">
            Comece em 3 passos
        </div>
        <div style="display:flex;gap:6px;align-items:center">
            {s1_html}
            <span style="color:#374151;font-size:14px">›</span>
            {s2_html}
            <span style="color:#374151;font-size:14px">›</span>
            {s3_html}
        </div>
        {"<div style='margin-top:0.45rem;font-size:0.8rem;color:#9CA3AF'>" + hint + "</div>" if hint else ""}
    </div>
    """, unsafe_allow_html=True)


# --- Global CSS ---
st.markdown("""
    <style>
    #GithubIcon {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden;}

    /* Minska Streamlits standardtomrum i toppen */
    .block-container { padding-top: 1.5rem !important; }

    /* Göm CookieController iframe */
    iframe[title="streamlit_cookies_controller.cookie_controller"] {
        display: none !important;
        height: 0 !important;
        width: 0 !important;
    }

    /* Blå accentfärg på flikar istället för Streamlit-rött */
    [data-baseweb="tab-highlight"] { background-color: #1a6de0 !important; }
    [data-baseweb="tab"][aria-selected="true"] { color: #1a6de0 !important; }

    /* Inloggad header — e-post + Sair i samma rad */
    .app-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.4rem 0 0.8rem 0;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 0.8rem;
    }
    .app-header .logo {
        font-size: 1.3rem;
        font-weight: 800;
        color: white;
    }
    .app-header .user-info {
        display: flex;
        align-items: center;
        gap: 1rem;
        font-size: 0.9rem;
        opacity: 0.7;
    }

    .hero {
        text-align: center;
        padding: 3rem 1rem 2rem 1rem;
    }
    .hero h1 {
        font-size: 2.6rem;
        font-weight: 800;
        line-height: 1.2;
        margin-bottom: 1rem;
    }
    .hero p {
        font-size: 1.15rem;
        opacity: 0.8;
        max-width: 560px;
        margin: 0 auto 1.8rem auto;
    }
    .cta-btn {
        display: inline-block;
        background: #1a6de0;
        color: white !important;
        text-decoration: none;
        padding: 14px 32px;
        border-radius: 8px;
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 0.6rem;
    }
    .cta-btn:hover { background: #1558b8; }
    .garantia {
        font-size: 0.85rem;
        opacity: 0.6;
        margin-top: 0.5rem;
    }
    .social-proof-bar {
        display: flex;
        justify-content: center;
        gap: 2rem;
        flex-wrap: wrap;
        background: rgba(26,109,224,0.08);
        border: 1px solid rgba(26,109,224,0.2);
        border-radius: 10px;
        padding: 0.9rem 1.5rem;
        margin: 0 auto 1.5rem auto;
        max-width: 640px;
        font-size: 0.95rem;
    }
    .social-proof-bar span {
        color: #e0e0e0;
        opacity: 0.9;
    }
    .social-proof-bar strong {
        color: #4d9fff;
    }
    .features {
        display: flex;
        gap: 1.2rem;
        justify-content: center;
        flex-wrap: wrap;
        margin: 2.5rem 0;
    }
    .feature-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 12px;
        padding: 1.4rem 1.2rem;
        max-width: 220px;
        text-align: center;
    }
    .feature-card .icon { font-size: 2rem; margin-bottom: 0.6rem; }
    .feature-card h3 { font-size: 1rem; font-weight: 700; margin-bottom: 0.4rem; }
    .feature-card p { font-size: 0.85rem; opacity: 0.7; margin: 0; }
    .steps {
        display: flex;
        gap: 1rem;
        justify-content: center;
        flex-wrap: wrap;
        margin: 1.5rem 0 2.5rem 0;
    }
    .step {
        text-align: center;
        max-width: 180px;
    }
    .step .num {
        width: 36px; height: 36px;
        border-radius: 50%;
        background: #1a6de0;
        color: white;
        font-weight: 700;
        font-size: 1rem;
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto 0.5rem auto;
    }
    .step h4 { font-size: 0.95rem; font-weight: 600; margin-bottom: 0.3rem; }
    .step p { font-size: 0.82rem; opacity: 0.7; margin: 0; }
    .price-box {
        text-align: center;
        background: rgba(26,109,224,0.1);
        border: 1px solid rgba(26,109,224,0.3);
        border-radius: 14px;
        padding: 2rem 1.5rem;
        max-width: 340px;
        margin: 0 auto 2rem auto;
    }
    .price-box .price { font-size: 2.2rem; font-weight: 800; }
    .price-box .per { font-size: 0.9rem; opacity: 0.6; margin-bottom: 1.2rem; }
    .price-box ul { list-style: none; padding: 0; margin: 0 0 1.4rem 0; text-align: left; }
    .price-box ul li { padding: 0.3rem 0; font-size: 0.92rem; }
    .section-title {
        text-align: center;
        font-size: 1.5rem;
        font-weight: 700;
        margin-bottom: 1.2rem;
    }

    /* Alla primärknapper — blå (#1a6de0) istället för Streamlits röda standard */
    .stButton > button[kind="primary"],
    .stFormSubmitButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        background-color: #1a6de0 !important;
        border-color: #1a6de0 !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stFormSubmitButton > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {
        background-color: #1558b8 !important;
        border-color: #1558b8 !important;
    }
    </style>
""", unsafe_allow_html=True)

if "user" not in st.session_state:
    st.session_state.user = None
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

# Capture acquisition params from URL once per session (set by worker.js JS snippet)
if "acquisition" not in st.session_state:
    _aqp = st.query_params
    st.session_state.acquisition = {
        "utm_source":   _aqp.get("utm_source", ""),
        "utm_medium":   _aqp.get("utm_medium", ""),
        "utm_campaign": _aqp.get("utm_campaign", ""),
        "ref":          _aqp.get("ref", ""),
        "device":       _aqp.get("device", ""),
        "anon_session": _aqp.get("anon_session", ""),
    }

# Sätt JWT på supabase-klienten vid varje rerun
if st.session_state.access_token:
    try:
        supabase.postgrest.auth(st.session_state.access_token)
    except Exception:
        pass
elif st.session_state.user is None:
    # Försök återställa session från cookie
    # Cookie-controllern laddar via iframe — vänta tills den är redo
    if "cookie_ready" not in st.session_state:
        st.session_state.cookie_ready = False

    if not st.session_state.cookie_ready:
        all_cookies = cookie.getAll()
        if all_cookies is None:
            # Inte redo än — rerun och vänta
            st.rerun()
        st.session_state.cookie_ready = True

    try:
        at = cookie.get("sb_access_token")
        rt = cookie.get("sb_refresh_token")
        if rt:
            res = None
            # Försök återställa med befintliga tokens
            if at:
                try:
                    res = supabase.auth.set_session(at, rt)
                except Exception:
                    pass
            # Fallback: refresh_session om set_session failade eller access token expirerat
            if not (res and res.user):
                try:
                    res = supabase.auth.refresh_session(rt)
                except Exception:
                    pass
            if res and res.user:
                st.session_state.user = res.user
                st.session_state.access_token = res.session.access_token
                st.session_state.refresh_token = res.session.refresh_token
                supabase.postgrest.auth(st.session_state.access_token)
                # Uppdatera cookies med förnyade tokens
                try:
                    cookie.set("sb_access_token", res.session.access_token, max_age=COOKIE_MAX_AGE)
                    cookie.set("sb_refresh_token", res.session.refresh_token, max_age=COOKIE_MAX_AGE)
                except Exception:
                    pass
                st.rerun()
    except Exception:
        pass

# =====================================================
# FEEDBACK — visas om ?feedback=up/down finns i URL
# =====================================================
_fb_params = st.query_params
_fb_type  = _fb_params.get("feedback")
_fb_email = _fb_params.get("email", "")

if _fb_type in ("up", "down"):
    st.markdown("<div style='font-size:1.3rem;font-weight:800;padding:1rem 0 1.5rem'>SEO Brasil 🌎</div>", unsafe_allow_html=True)

    if _fb_type == "up":
        if "fb_logged" not in st.session_state:
            try:
                supabase.table("email_feedback").insert({
                    "email": _fb_email, "rating": "up"
                }).execute()
            except Exception:
                pass
            st.session_state.fb_logged = True
        st.success("Obrigado! Fico feliz que o relatório foi útil. 😊")
        st.caption("Você pode fechar esta aba.")

    else:  # down
        if st.session_state.get("fb_done"):
            st.success("Obrigado pelo feedback! Vamos melhorar. 🙏")
            st.caption("Você pode fechar esta aba.")
        else:
            st.warning("Que pena! Nos conte o que poderia ser melhor:")
            comment = st.text_area(
                "",
                placeholder="O que faltou no relatório desta semana?",
                label_visibility="collapsed",
                height=120,
            )
            if st.button("Enviar feedback", type="primary"):
                if comment.strip():
                    try:
                        supabase.table("email_feedback").insert({
                            "email": _fb_email,
                            "rating": "down",
                            "comment": comment.strip(),
                        }).execute()
                    except Exception:
                        pass
                    st.session_state.fb_done = True
                    st.rerun()
                else:
                    st.warning("Escreva algo antes de enviar.")

    st.stop()

# =====================================================
# TRIAL CHECK — körs om användaren är inloggad
# =====================================================
if st.session_state.user is not None:
    _trial_email = st.session_state.user.email
    _trial_status = get_trial_status(_trial_email)

    if _trial_status == "TRIAL_EXPIRED":
        if "trial_expired_event_logged" not in st.session_state:
            log_event(st.session_state.user.id, "trial_expired_shown")
            st.session_state.trial_expired_event_logged = True
        st.markdown("<div style='font-size:1.3rem;font-weight:800;padding:1rem 0 1.5rem'>SEO Brasil 🌎</div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='text-align:center;padding:2rem 1rem;'>
            <div style='font-size:2.5rem;margin-bottom:1rem;'>🔒</div>
            <h2 style='margin-bottom:0.5rem;'>Seu período de teste de 14 dias terminou!</h2>
            <p style='color:#888;margin-bottom:2rem;max-width:480px;margin-left:auto;margin-right:auto;'>
                Para continuar recebendo seus relatórios semanais e descobrindo
                palavras-chave de alta conversão, assine o plano completo.
            </p>
        </div>
        """, unsafe_allow_html=True)
        hotmart_url_with_email = f"https://pay.hotmart.com/L106736067M?email={_trial_email}"
        st.link_button("👉 Assinar por R$197/mês na Hotmart", hotmart_url_with_email, type="primary", use_container_width=True)
        st.stop()

# =====================================================
# NÃO LOGADO — Landningssida
# =====================================================
if st.session_state.user is None:

    # ── INVITE TOKEN FLOW ─────────────────────────────────────────────────────
    _invite_token = st.query_params.get("invite_token")
    if _invite_token:
        # Validate: exists, unused, not expired
        _tok_valid = False
        try:
            _tok_res = supabase.table("invite_tokens").select("*") \
                .eq("token", _invite_token).is_("used_at", "null").execute()
            if _tok_res.data:
                _tok_exp = datetime.fromisoformat(
                    _tok_res.data[0]["expires_at"].replace("Z", "+00:00")
                )
                if _tok_exp > datetime.now(timezone.utc):
                    _tok_valid = True
        except Exception:
            pass

        st.markdown(
            "<div style='font-size:1.3rem;font-weight:800;padding:1rem 0 1.5rem'>"
            "SEO Brasil 🌎</div>",
            unsafe_allow_html=True,
        )

        if not _tok_valid:
            st.error("Este link de convite é inválido, expirou ou já foi utilizado.")
            st.markdown(
                f"<div style='text-align:center;margin-top:1.2rem;font-size:0.92rem;opacity:0.75'>"
                f"Já tem uma conta? <a href='https://seobrasil.app' "
                f"style='color:#4d9fff;text-decoration:none;font-weight:600'>Fazer login →</a></div>",
                unsafe_allow_html=True,
            )
            st.stop()

        st.markdown("""
        <div style="text-align:center;padding:1.5rem 1rem 0.5rem 1rem">
            <div style='font-size:1.5rem;margin-bottom:0.5rem'>🎉</div>
            <h2 style='margin-bottom:0.4rem;font-size:1.6rem;'>Você foi convidado!</h2>
            <p style='opacity:0.7;max-width:420px;margin:0 auto;font-size:0.95rem;'>
            Crie sua conta e comece seu teste gratuito de 14 dias — sem cartão de crédito.
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("invite_form"):
            inv_email = st.text_input("E-mail")
            inv_senha = st.text_input("Senha (mín. 6 caracteres)", type="password")
            inv_submit = st.form_submit_button(
                "Criar conta e começar →", type="primary", use_container_width=True
            )

        if inv_submit:
            if not inv_email or not inv_senha:
                st.error("Preencha e-mail e senha.")
            elif len(inv_senha) < 6:
                st.error("A senha deve ter pelo menos 6 caracteres.")
            else:
                # Mark token as used first (prevent double-use)
                try:
                    supabase.table("invite_tokens").update({
                        "used_at": datetime.now(timezone.utc).isoformat()
                    }).eq("token", _invite_token).execute()
                except Exception:
                    st.error("Erro ao validar o convite. Tente novamente.")
                    st.stop()

                _ok, _err = create_trial_account(inv_email, inv_senha)
                if _ok:
                    st.rerun()
                else:
                    # Un-mark token so the same link can be retried
                    try:
                        supabase.table("invite_tokens").update(
                            {"used_at": None}
                        ).eq("token", _invite_token).execute()
                    except Exception:
                        pass
                    if _err == "DUPLICATE":
                        st.error("Este e-mail já está cadastrado.")
                        st.markdown(
                            "<div style='text-align:center;margin-top:0.8rem'>"
                            "<a href='https://seobrasil.app' style='color:#4d9fff;font-weight:600'>"
                            "Ir para o login →</a></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.error("Erro ao criar conta. Tente novamente.")

        st.stop()
    # ── FIM INVITE TOKEN FLOW ─────────────────────────────────────────────────

    # --- Social proof ---
    kw_count = get_social_proof()

    # --- Hotmart-banner högst upp (vid redirect från köpflödet) ---
    if st.query_params.get("source") == "hotmart":
        st.markdown("""
        <div style="background:rgba(26,224,109,0.1);border:1px solid rgba(26,224,109,0.35);
        border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem;text-align:center">
            <strong style="color:#4dff99;font-size:1rem">🎉 Sua compra foi recebida!</strong><br>
            <span style="font-size:0.9rem;opacity:0.85">
            A ativação da conta leva cerca de 1 a 2 minutos.<br>
            Você receberá um e-mail para definir sua senha — verifique também a caixa de spam.
            </span>
        </div>
        """, unsafe_allow_html=True)

    # --- Hero ---
    st.markdown(f"""
    <div class="hero">
        <h1>Descubra o que o Brasil<br>está buscando no Google</h1>
        <p>Pesquise palavras-chave, encontre oportunidades e acompanhe as posições do seu site no Google.</p>
        <div class="social-proof-bar">
            <span>🔍 <strong>+{kw_count:,}</strong> palavras-chave analisadas</span>
            <span>📈 Dados atualizados toda semana</span>
            <span>🇧🇷 Focado no mercado brasileiro</span>
        </div>
        <a class="cta-btn" href="javascript:void(0)" onclick="(function(){{var el=document.getElementById('comecar');if(el)el.scrollIntoView({{behavior:'smooth'}});else window.scrollTo({{top:999,behavior:'smooth'}});}})();">Comece grátis por 14 dias →</a>
        <div class="garantia">Sem cartão de crédito • Cancele quando quiser</div>
        <div style="margin-top:1.2rem;font-size:0.9rem;opacity:0.65">
            Já tem uma conta?
            <a href="javascript:void(0)"
               onclick="(function(){{var el=document.getElementById('login-section');if(el)el.scrollIntoView({{behavior:'smooth'}});else window.scrollTo({{top:9999,behavior:'smooth'}});}})();"
               style="color:#4d9fff;text-decoration:none;font-weight:600">Entrar aqui ↓</a>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- Trial grátis self-service (sem precisar de convite manual) ---
    st.markdown('<div id="comecar"></div>', unsafe_allow_html=True)
    _left, _mid, _right = st.columns([1, 2, 1])
    with _mid:
        with st.expander("🎁 Comece grátis por 14 dias — sem cartão de crédito", expanded=True):
            st.caption("Crie sua conta agora e use o SEO Brasil por 14 dias, sem compromisso.")
            with st.form("public_trial_form"):
                pt_email = st.text_input("E-mail", key="pt_email")
                pt_senha = st.text_input("Senha (mín. 6 caracteres)", type="password", key="pt_senha")
                pt_submit = st.form_submit_button("Criar conta grátis →", type="primary", use_container_width=True)

            if pt_submit:
                if not pt_email or not pt_senha:
                    st.error("Preencha e-mail e senha.")
                elif len(pt_senha) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    _ok, _err = create_trial_account(pt_email, pt_senha)
                    if _ok:
                        st.rerun()
                    elif _err == "DUPLICATE":
                        st.error("Este e-mail já está cadastrado. Faça login abaixo (\"Entrar aqui\").")
                    else:
                        st.error("Erro ao criar conta. Tente novamente em instantes.")

    st.divider()

    # --- Features ---
    st.markdown('<div class="section-title">Por que SEO Brasil?</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="features">
        <div class="feature-card">
            <div class="icon">🌎</div>
            <h3>Dados reais do Brasil</h3>
            <p>Volume de busca, CPC e competição focados no mercado brasileiro.</p>
        </div>
        <div class="feature-card">
            <div class="icon">📈</div>
            <h3>Monitoramento de posições</h3>
            <p>Acompanhe a posição do seu site no Google para as palavras-chave que você escolher.</p>
        </div>
        <div class="feature-card">
            <div class="icon">📊</div>
            <h3>Exporte para CSV</h3>
            <p>Baixe todos os dados e use em planilhas, relatórios ou para clientes.</p>
        </div>
        <div class="feature-card">
            <div class="icon">🎯</div>
            <h3>Até 10 palavras de uma vez</h3>
            <p>Pesquise múltiplas palavras-chave em uma única busca.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- Video demo ---
    st.markdown('<div class="section-title">Veja o SEO Brasil em ação</div>', unsafe_allow_html=True)
    st.video("comparacao.mp4")

    st.divider()

    # --- Como funciona ---
    st.markdown('<div class="section-title">Como funciona</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="steps">
        <div class="step">
            <div class="num">1</div>
            <h4>Adicione seu site</h4>
            <p>Informe o endereço do seu domínio — é assim que o sistema sabe qual site está monitorando no Google.</p>
        </div>
        <div class="step">
            <div class="num">2</div>
            <h4>Pesquise e rastreie palavras-chave</h4>
            <p>Use a ferramenta de pesquisa para ver volume, CPC e competição de qualquer termo. Clique em + Rastrear nos que quer monitorar.</p>
        </div>
        <div class="step">
            <div class="num">3</div>
            <h4>Monitoramos sua posição automaticamente</h4>
            <p>Toda semana o sistema consulta o Google e registra em que posição seu site aparece para cada palavra-chave rastreada.</p>
        </div>
        <div class="step">
            <div class="num">4</div>
            <h4>Você recebe seu relatório</h4>
            <p>Toda segunda-feira: um e-mail com a evolução das posições — o que subiu, o que caiu e o que ficou estável.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- Preço ---
    st.markdown('<div class="section-title">Plano único</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="price-box">
        <div class="price">R$197</div>
        <div class="per">por mês</div>
        <ul>
            <li>✅ Pesquisa ilimitada de palavras-chave</li>
            <li>✅ Monitoramento de até 20 palavras-chave</li>
            <li>✅ Dados do mercado brasileiro</li>
            <li>✅ Exportação CSV</li>
            <li>✅ Relatórios semanais no seu e-mail</li>
            <li>✅ Cancele quando quiser</li>
        </ul>
        <a class="cta-btn" href="{HOTMART_URL}">Assinar agora →</a>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- Login ---
    st.markdown('<div id="login-section"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Acesse sua conta</div>', unsafe_allow_html=True)

    with st.form("login_form"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if entrar:
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": senha})
            st.session_state.user = res.user
            st.session_state.access_token = res.session.access_token
            st.session_state.refresh_token = res.session.refresh_token
            supabase.postgrest.auth(res.session.access_token)
            # Uppdatera last_login + user_id (fylls i vid första inlogg efter Hotmart-köp)
            try:
                supabase.table("subscribers").update({
                    "last_login": datetime.now(timezone.utc).isoformat(),
                    "user_id": str(res.user.id),
                }).eq("email", email).execute()
            except Exception:
                pass
            # Sätt cookies för persistent session
            try:
                cookie.set("sb_access_token", res.session.access_token, max_age=COOKIE_MAX_AGE)
                cookie.set("sb_refresh_token", res.session.refresh_token, max_age=COOKIE_MAX_AGE)
            except Exception:
                pass
            log_event(res.user.id, "user_login")
            st.rerun()
        except Exception:
            st.error("E-mail ou senha incorretos.")

    st.markdown(f"""
    <div style="text-align:center;margin-top:1.2rem;font-size:0.92rem;opacity:0.75">
    Ainda não tem uma conta? <a href="{HOTMART_URL}" style="color:#4d9fff;text-decoration:none;font-weight:600">Assine agora →</a>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("Esqueceu a senha?"):
        email_reset = st.text_input("Digite seu e-mail para redefinir a senha", key="reset_email")
        if st.button("Enviar link de redefinição"):
            if email_reset:
                try:
                    supabase.auth.reset_password_for_email(
                        email_reset,
                        options={"redirect_to": "https://app.seobrasil.app"}
                    )
                    st.success("Link enviado! Verifique sua caixa de entrada.")
                except Exception:
                    st.error("Erro ao enviar. Verifique o e-mail digitado.")
            else:
                st.warning("Digite seu e-mail primeiro.")

# =====================================================
# LOGADO
# =====================================================
else:
    prenumerant = ar_prenumerant(st.session_state.user.email)
    user_id = st.session_state.user.id

    # Log subscription_activated once when account is 'active' — catches webhook/manual activations
    try:
        _sub_row = supabase.table("subscribers").select("subscription_status").eq("email", st.session_state.user.email).execute()
        if _sub_row.data and _sub_row.data[0].get("subscription_status") == "active":
            if not has_event(user_id, "subscription_activated"):
                log_event(user_id, "subscription_activated")
    except Exception:
        pass

    # --- Scrolla till toppen ---
    st.markdown("""<script>
    setTimeout(function(){
        var el = window.parent.document.querySelector('section.main');
        if(el) el.scrollTop = 0;
        window.parent.scrollTo(0,0);
    }, 150);
    </script>""", unsafe_allow_html=True)

    # --- Kompakt header med logo + email + Sair i samma rad ---
    col_logo, col_user, col_sair = st.columns([3, 4, 1])
    with col_logo:
        st.markdown("<div style='font-size:1.3rem;font-weight:800;padding-top:6px'>SEO Brasil 🌎</div>", unsafe_allow_html=True)
    with col_user:
        st.markdown(f"<div style='font-size:0.85rem;opacity:0.6;padding-top:10px;text-align:right'>{st.session_state.user.email}</div>", unsafe_allow_html=True)
    with col_sair:
        sair_clicked = st.button("Sair", key="sair_btn")

    if sair_clicked:
        try:
            cookie.remove("sb_access_token")
            cookie.remove("sb_refresh_token")
        except Exception:
            pass
        st.session_state.user = None
        st.rerun()

    st.divider()

    if prenumerant:

        # Initiera session state för sökresultat
        if "search_results" not in st.session_state:
            st.session_state.search_results = None
        if "keyword_ideas" not in st.session_state:
            st.session_state.keyword_ideas = []
        if "ranking_in_progress" not in st.session_state:
            st.session_state.ranking_in_progress = False
        if "ranking_done" not in st.session_state:
            st.session_state.ranking_done = False
        if "_ranking_kws" not in st.session_state:
            st.session_state._ranking_kws = []
        if "_ranking_viewed_logged" not in st.session_state:
            st.session_state._ranking_viewed_logged = False

        # --- Onboarding-banner: visa om ingen domän är satt ---
        _ob_email = st.session_state.user.email
        _ob_domain = get_user_domain(_ob_email)

        if not _ob_domain:
            st.markdown("""
            <div style="background:rgba(26,109,224,0.12);border:1px solid rgba(26,109,224,0.35);
            border-radius:10px;padding:0.9rem 1.2rem;margin-bottom:0.5rem">
                <strong style="color:#4d9fff">🚀 Configure seu site para monitorar seu ranking</strong><br>
                <span style="font-size:0.87rem;opacity:0.8">
                Adicione o endereço do seu site uma única vez e acompanhe sua posição no Google toda segunda-feira.
                </span>
            </div>
            """, unsafe_allow_html=True)
            col_ob, col_ob_btn = st.columns([4, 1])
            with col_ob:
                ob_domain_val = st.text_input("", placeholder="meusite.com.br",
                                              key="onboard_domain_input",
                                              label_visibility="collapsed")
            with col_ob_btn:
                if st.button("Salvar site", key="onboard_save_btn"):
                    if ob_domain_val.strip():
                        save_user_domain(_ob_email, ob_domain_val)
                        log_event(user_id, "domain_added")
                        st.success("✅ Site salvo!")
                        st.rerun()
            st.divider()

        # ── ONBOARDING PROGRESS ───────────────────────────
        _ob_status = get_onboarding_status(
            user_id, _ob_domain, st.session_state.ranking_in_progress
        )
        render_onboarding_progress(_ob_status)

        tab1, tab2 = st.tabs(["🔍 Pesquisa de palavras-chave", "📈 Meu Monitoramento"])

        # ── TAB 1: SÖKNING ──────────────────────────────
        with tab1:

            # ── ON-DEMAND INITIAL RANKING ─────────────────
            if st.session_state.ranking_in_progress:
                _rank_domain = get_user_domain(st.session_state.user.email)
                _rank_kws = st.session_state._ranking_kws
                if _rank_domain and _rank_kws:
                    st.markdown(
                        "<div style='font-weight:700;font-size:1rem;margin-bottom:0.5rem'>"
                        "🔍 Verificando suas posições no Google...</div>",
                        unsafe_allow_html=True,
                    )
                    _status_el = st.empty()
                    _progress_bar = st.progress(0)
                    log_event(user_id, "initial_ranking_started", {"keyword_count": len(_rank_kws)})
                    _ranking_results = run_on_demand_ranking(
                        user_id, _rank_domain, _rank_kws,
                        DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
                        _status_el, _progress_bar,
                    )
                    log_event(user_id, "initial_ranking_completed",
                              {"results": {k: v["position"] for k, v in _ranking_results.items()}})
                    st.session_state.ranking_in_progress = False
                    st.session_state.ranking_done = True
                    st.rerun()

            if st.session_state.ranking_done:
                st.success("✅ Seu primeiro ranking está pronto! Veja os resultados em **Meu Monitoramento**.")

            sokord_text = st.text_area(
                "Digite as palavras-chave (uma por linha, máx 10):",
                placeholder="agencia de marketing Sao Paulo\nseo para pequenas empresas\nmarketing digital Brasil",
                height=180
            )

            if st.button("Buscar"):
                # Säkerställ att JWT är satt på supabase-klienten inför sökning
                if st.session_state.access_token:
                    try:
                        supabase.postgrest.auth(st.session_state.access_token)
                    except Exception:
                        pass
                sokordslista = [s.strip() for s in sokord_text.split("\n") if s.strip()][:10]
                if not sokordslista:
                    st.warning("Digite ao menos uma palavra-chave.")
                else:
                    with st.spinner(f"Buscando dados para {len(sokordslista)} palavra(s)-chave..."):
                        try:
                            items = get_keyword_data(sokordslista, supabase, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD)
                            st.session_state.search_results = items
                            log_event(user_id, "keyword_searched", {"count": len(sokordslista)})
                        except Exception:
                            st.error("Erro ao buscar dados. Verifique sua conexão e tente novamente.")
                            st.session_state.search_results = None

                    if st.session_state.search_results:
                        with st.spinner("Buscando sugestões relacionadas..."):
                            try:
                                ideas = get_keyword_ideas(
                                    sokordslista, supabase, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, limit=10
                                )
                                searched_set = {kw.lower() for kw in sokordslista}
                                st.session_state.keyword_ideas = [
                                    i for i in ideas if i["keyword"].lower() not in searched_set
                                ]
                            except Exception as _ideas_err:
                                st.session_state.keyword_ideas = []

            # Visa resultat med "+ Rastrear"-knappar
            if st.session_state.search_results:
                items = st.session_state.search_results
                tracked_set = get_tracked_set(user_id)

                csv_rows = []
                for item in items:
                    kw = item.get("keyword", "")
                    volume = item.get("search_volume") or 0
                    cpc = item.get("cpc") or 0
                    comp = str(item.get("competition", "N/A")).capitalize()
                    volume_fmt = f"{int(volume):,}".replace(",", ".")
                    cpc_fmt = f"{float(cpc):.2f}" if cpc else "N/A"

                    csv_rows.append({
                        "Palavra-chave": kw,
                        "Volume/mês": volume_fmt,
                        "Competição": comp,
                        "CPC médio (R$)": cpc_fmt,
                    })

                    col_info, col_btn = st.columns([7, 2])
                    with col_info:
                        st.markdown(f"""
                        <div style="background:#1e1e1e;border-radius:8px;padding:10px 14px;
                                    display:flex;flex-wrap:wrap;align-items:center;gap:6px 16px;
                                    margin-bottom:2px">
                            <span style="color:white;font-size:14px;font-weight:500;flex:1 0 100%">{kw}</span>
                            <span style="color:#9CA3AF;font-size:13px">
                                <span style="color:#6B7280;font-size:11px">Vol. </span>{volume_fmt}
                            </span>
                            <span style="color:#9CA3AF;font-size:13px">
                                <span style="color:#6B7280;font-size:11px">Comp. </span>{comp}
                            </span>
                            <span style="color:#9CA3AF;font-size:13px">
                                <span style="color:#6B7280;font-size:11px">CPC </span>R${cpc_fmt}
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_btn:
                        if kw in tracked_set:
                            st.markdown("<div style='padding-top:10px;color:#4CAF50;font-size:13px'>✅</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='padding-top:6px'>", unsafe_allow_html=True)
                            if st.button("+ Rastrear", key=f"track_{kw}",
                                         disabled=st.session_state.ranking_in_progress):
                                ok, msg = add_tracking(kw, user_id)
                                if ok:
                                    log_event(user_id, "keyword_saved", {"keyword": kw})
                                    if not has_event(user_id, "keyword_tracked"):
                                        log_event(user_id, "keyword_tracked", {"keyword": kw})
                                    _user_domain = get_user_domain(st.session_state.user.email)
                                    if _user_domain and not has_any_rankings(user_id):
                                        _all_kws = get_tracked_keywords_list(user_id)
                                        st.session_state._ranking_kws = [r["keyword"] for r in _all_kws]
                                        st.session_state.ranking_in_progress = True
                                        st.session_state.ranking_done = False
                                    else:
                                        st.info("📅 Nosso robô analisa as posições toda segunda-feira de manhã. Seu primeiro relatório chega na próxima segunda.")
                                    st.rerun()
                                else:
                                    st.error(msg)
                            st.markdown("</div>", unsafe_allow_html=True)

                st.divider()
                df_csv = pd.DataFrame(csv_rows)
                csv = df_csv.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    label="📥 Exportar para CSV",
                    data=csv,
                    file_name="seo_brasil.csv",
                    mime="text/csv",
                )

                # --- Debug ---

                # --- Sugestões relacionadas ---
                ideas = st.session_state.get("keyword_ideas", [])
                if ideas:
                    def _is_opportunity(idea):
                        return (idea.get("search_volume") or 0) > 10000 and float(idea.get("cpc") or 0) < 0.25

                    def _seo_difficulty(cpc):
                        cpc = float(cpc or 0)
                        if cpc < 0.25:
                            return "Low", "#2ecc71"
                        elif cpc < 0.75:
                            return "Medium", "#f0a500"
                        else:
                            return "High", "#9CA3AF"

                    ideas_sorted = sorted(
                        ideas,
                        key=lambda x: (not _is_opportunity(x), -(x.get("search_volume") or 0))
                    )

                    st.divider()
                    st.markdown(
                        "<div style='font-weight:700;font-size:1rem;margin-bottom:0.4rem'>"
                        "💡 Sugestões relacionadas</div>",
                        unsafe_allow_html=True,
                    )
                    for idea in ideas_sorted:
                        ikw      = idea.get("keyword", "")
                        ivol     = idea.get("search_volume") or 0
                        icpc     = idea.get("cpc") or 0
                        ivol_fmt = f"{int(ivol):,}".replace(",", ".")
                        icpc_fmt = f"{float(icpc):.2f}" if icpc else "N/A"
                        is_opp   = _is_opportunity(idea)
                        diff_label, diff_color = _seo_difficulty(icpc)
                        border   = "#2ecc71" if is_opp else "#1a6de0"
                        badge    = (
                            "<span style='background:#0d2b1a;color:#2ecc71;font-size:11px;"
                            "padding:2px 7px;border-radius:4px;font-weight:600;margin-left:6px'>"
                            "🎯 Oportunidade</span>"
                        ) if is_opp else ""

                        col_info, col_btn = st.columns([7, 2])
                        with col_info:
                            st.markdown(f"""
                            <div style="background:#1a1a2e;border-radius:8px;padding:10px 14px;
                                        display:flex;flex-wrap:wrap;align-items:center;gap:6px 16px;
                                        margin-bottom:2px;border-left:3px solid {border}">
                                <span style="color:white;font-size:14px;font-weight:500;flex:1 0 100%">{ikw}{badge}</span>
                                <span style="color:#9CA3AF;font-size:13px">
                                    <span style="color:#6B7280;font-size:11px">Vol. </span>{ivol_fmt}
                                </span>
                                <span style="color:#9CA3AF;font-size:13px">
                                    <span style="color:#6B7280;font-size:11px">Dificuldade SEO </span>
                                    <span style="color:{diff_color}">{diff_label}</span>
                                </span>
                                <span style="color:#9CA3AF;font-size:13px">
                                    <span style="color:#6B7280;font-size:11px">CPC </span>R${icpc_fmt}
                                </span>
                            </div>
                            """, unsafe_allow_html=True)
                        with col_btn:
                            if ikw in tracked_set:
                                st.markdown(
                                    "<div style='padding-top:10px;color:#4CAF50;font-size:13px'>✅</div>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown("<div style='padding-top:6px'>", unsafe_allow_html=True)
                                if st.button("+ Rastrear", key=f"track_idea_{ikw}",
                                             disabled=st.session_state.ranking_in_progress):
                                    ok, msg = add_tracking(ikw, user_id)
                                    if ok:
                                        log_event(user_id, "keyword_saved", {"keyword": ikw})
                                        if not has_event(user_id, "keyword_tracked"):
                                            log_event(user_id, "keyword_tracked", {"keyword": ikw})
                                        _user_domain = get_user_domain(st.session_state.user.email)
                                        if _user_domain and not has_any_rankings(user_id):
                                            _all_kws = get_tracked_keywords_list(user_id)
                                            st.session_state._ranking_kws = [r["keyword"] for r in _all_kws]
                                            st.session_state.ranking_in_progress = True
                                            st.session_state.ranking_done = False
                                        else:
                                            st.info("📅 Nosso robô analisa as posições toda segunda-feira de manhã. Seu primeiro relatório chega na próxima segunda.")
                                        st.rerun()
                                    else:
                                        st.error(msg)
                                st.markdown("</div>", unsafe_allow_html=True)

        # ── TAB 2: MIN ÖVERVAKNING ───────────────────────
        with tab2:
            user_email = st.session_state.user.email
            domain = get_user_domain(user_email)
            if not st.session_state.get("_ranking_viewed_logged"):
                log_event(user_id, "ranking_viewed")
                st.session_state._ranking_viewed_logged = True

            # --- Domän-input ---
            if not domain:
                st.info("💡 Adicione o endereço do seu site para monitorar sua posição no Google.")
                col_d, col_b = st.columns([4, 1])
                with col_d:
                    new_domain = st.text_input("", placeholder="seobrasil.app", key="domain_input", label_visibility="collapsed")
                with col_b:
                    if st.button("Salvar site", key="save_domain"):
                        if new_domain.strip():
                            save_user_domain(user_email, new_domain)
                            log_event(user_id, "domain_added")
                            st.success("✅ Site salvo!")
                            st.rerun()
            else:
                col_d, col_b = st.columns([5, 1])
                with col_d:
                    st.markdown(f"🌐 **Seu site:** `{domain}`")
                with col_b:
                    if st.button("Alterar", key="change_domain"):
                        supabase.table("subscribers").update({"domain": None}).eq("email", user_email).execute()
                        st.rerun()

            st.divider()

            tracked_list = get_tracked_keywords_list(user_id)

            # ranking_viewed: loggas en gång — kräver domän, trackade keywords och faktisk ranking-data
            if domain and tracked_list and not has_event(user_id, "ranking_viewed"):
                try:
                    _has_rankings = supabase.table("keyword_rankings").select("id").eq("user_id", str(user_id)).limit(1).execute()
                    if _has_rankings.data:
                        log_event(user_id, "ranking_viewed")
                except Exception:
                    pass

            if domain:
                st.caption("📌 Para receber seu relatório semanal, pesquise palavras-chave e clique em '+ Rastrear' nas que deseja monitorar.")

            if not tracked_list:
                st.info("Você ainda não rastreou nenhuma palavra-chave. Pesquise e clique em '+ Rastrear' para começar!")
            else:
                count = len(tracked_list)
                st.caption(f"{count}/20 palavras rastreadas — dados atualizados toda segunda-feira")
                st.divider()

                for item in tracked_list:
                    kw = item["keyword"]
                    rank_row = get_rank_data_for_keyword(user_id, kw, domain)
                    trend = trend_label(rank_row)

                    col_kw, col_del = st.columns([9, 1])
                    with col_kw:
                        st.markdown(f"""
                        <div style="background:#1e1e1e;border-radius:8px;padding:10px 14px;
                                    display:flex;justify-content:space-between;align-items:center;
                                    margin-bottom:6px">
                            <span style="color:white;font-size:14px;font-weight:500;
                                         flex:1;margin-right:10px">{kw}</span>
                            <span style="color:#9CA3AF;font-size:13px;
                                         white-space:nowrap">{trend}</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_del:
                        if st.button("✕", key=f"del_{kw}", help=f"Remover '{kw}'"):
                            remove_tracking(kw, user_id)
                            st.rerun()

    else:
        st.info("✨ Acesso completo por R$197/mês — relatórios automáticos toda segunda-feira.")
        st.markdown(f'<a href="{HOTMART_URL}" target="_blank"><button style="background:#1a6de0;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:15px;">Assinar agora → R$197/mês</button></a>', unsafe_allow_html=True)

st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro | Suporte: samuel@seobrasil.app")

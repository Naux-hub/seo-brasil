import streamlit as st
import pandas as pd
import requests
import time
import os
from supabase import create_client
from keyword_cache import get_keyword_data, get_keyword_ideas
from domain_opportunities import (
    fetch_catchdoms, enrich_with_dataforseo, merge_results,
    compact_num, tf_cf_ratio, registro_br_url, wayback_url, majestic_url,
    MAJESTIC_CATEGORIES,
)
from datetime import datetime, timedelta, timezone
from streamlit_cookies_controller import CookieController
import streamlit.components.v1 as components
from urllib.parse import quote as urlquote
import logging

DATAFORSEO_LOGIN = os.environ["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = os.environ["DATAFORSEO_PASSWORD"]
AHREFS_API_KEY = os.environ.get("AHREFS_API_KEY", "")
CATCHDOMS_TOKEN = os.environ.get("CATCHDOMS_TOKEN", "")
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

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
    if len(count_res.data) >= 100:
        return False, "Limite de 100 palavras atingido."
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

def get_user_domain(email, access_token=None):
    _pg = supabase.postgrest.auth(access_token) if access_token else supabase.postgrest
    res = _pg.from_("subscribers").select("domain").eq("email", email).execute()
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
            f"{os.environ['SUPABASE_URL']}/auth/v1/admin/users",
            headers={
                "apikey": os.environ["SUPABASE_KEY"],
                "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}",
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
        st.session_state['_gads_conv'] = True
        return True, None
    except Exception as e:
        _err_str = str(e).lower()
        if any(x in _err_str for x in ("already", "duplicate")):
            return False, "DUPLICATE"
        return False, str(e)

def save_user_domain(email, domain):
    domain = domain.strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    # Nollställ domain health-cache när domänen ändras — ny domän kräver ny hämtning
    supabase.table("subscribers").update({
        "domain": domain,
        "domain_rank": None,
        "spam_score": None,
        "ahrefs_dr": None,
        "domain_enriched_at": None,
    }).eq("email", email).execute()


# ── DOMAIN HEALTH (Domain Rank + Spam Score + Ahrefs DR) ─────────────────────

_DOMAIN_HEALTH_TTL_DAYS    = 30   # Auto-refresh efter 30 dagar
_DOMAIN_HEALTH_THROTTLE_DAYS = 7  # Manuell refresh: minst 7 dagar mellan anrop


def fetch_ahrefs_dr(domain, api_key):
    """
    Anropar Ahrefs gratis Domain Rating-endpoint (kostnadsfri, kräver gratis APIv3-nyckel).
    GET /v3/public/domain-rating-free?target={domain}

    Returnerar float (0.0–100.0) eller None vid fel/saknad nyckel.
    DR=0.0 bevaras — indikerar att Ahrefs inte registrerat backlinks för domänen.
    Kastar inga undantag utåt.

    Licens: http://ahrefs.com/legal/domain-rating-license
    Attribution krävs i UI: "Domain Rating by Ahrefs" (https://ahrefs.com/)
    """
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://api.ahrefs.com/v3/public/domain-rating-free",
            params={"target": domain},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            dr_obj = (data.get("domain_rating") or {})
            dr_val = dr_obj.get("domain_rating")
            if dr_val is not None:
                return float(dr_val)
    except Exception:
        logging.exception("[ahrefs_dr] fetch fel: domain=%s", domain)
    return None


def fetch_domain_health(domain, login, password):
    """
    Anropar DataForSEO + Ahrefs:
      POST /v3/backlinks/bulk_ranks/live       → domain_rank (int|None)
      POST /v3/backlinks/bulk_spam_score/live  → spam_score  (int|None)
      GET  Ahrefs /v3/public/domain-rating-free → ahrefs_dr (float|None)

    Returnerar (domain_rank, spam_score, ahrefs_dr).
    DR=0 bevaras som 0 — inte None.
    SS=None bevaras om domänen saknas i svaret.
    Kastar inga undantag utåt — returnerar (None, None, None) vid totalt fel.
    """
    dr = None
    ss = None

    # --- Domain Rank ---
    try:
        r = requests.post(
            "https://api.dataforseo.com/v3/backlinks/bulk_ranks/live",
            auth=(login, password),
            json=[{"targets": [domain], "rank_scale": "one_hundred"}],
            timeout=30,
        )
        data = r.json()
        if data.get("status_code") == 20000:
            task = (data.get("tasks") or [{}])[0]
            if task.get("status_code") == 20000:
                items = []
                for result_block in (task.get("result") or []):
                    items.extend(result_block.get("items") or [])
                for item in items:
                    if item.get("target") == domain:
                        dr = item.get("rank")   # 0 är giltigt värde
                        break
    except Exception:
        logging.exception("[domain_health] bulk_ranks fel: domain=%s", domain)

    # --- Spam Score ---
    try:
        r2 = requests.post(
            "https://api.dataforseo.com/v3/backlinks/bulk_spam_score/live",
            auth=(login, password),
            json=[{"targets": [domain]}],
            timeout=30,
        )
        data2 = r2.json()
        if data2.get("status_code") == 20000:
            task2 = (data2.get("tasks") or [{}])[0]
            if task2.get("status_code") == 20000:
                items2 = []
                for result_block2 in (task2.get("result") or []):
                    items2.extend(result_block2.get("items") or [])
                for item2 in items2:
                    if item2.get("target") == domain:
                        ss = item2.get("spam_score")  # None bevaras om saknas
                        break
    except Exception:
        logging.exception("[domain_health] bulk_spam_score fel: domain=%s", domain)

    ahrefs_dr = fetch_ahrefs_dr(domain, AHREFS_API_KEY)

    return dr, ss, ahrefs_dr


def get_domain_health(email, domain):
    """
    Läser domain_rank, spam_score, ahrefs_dr, domain_enriched_at från subscribers.
    Hämtar från DataForSEO + Ahrefs om cache saknas eller är äldre än 30 dagar.

    Returnerar dict: {domain_rank, spam_score, ahrefs_dr, domain_enriched_at} eller None.
    Kastar aldrig undantag utåt.
    """
    if not domain:
        return None
    try:
        res = supabase.table("subscribers").select(
            "domain_rank,spam_score,ahrefs_dr,domain_enriched_at"
        ).eq("email", email).execute()
        if not res.data:
            return None
        row = res.data[0]
    except Exception:
        logging.exception("[domain_health] get: read fel email=%s", email)
        return None

    dr            = row.get("domain_rank")          # None eller int (0 giltigt)
    ss            = row.get("spam_score")            # None eller int
    ahrefs_dr     = row.get("ahrefs_dr")             # None eller float (0.0 giltigt)
    enriched_str  = row.get("domain_enriched_at")

    enriched_at   = None
    needs_fetch   = True

    if enriched_str:
        try:
            enriched_at = datetime.fromisoformat(enriched_str.replace("Z", "+00:00"))
            days_since  = (datetime.now(timezone.utc) - enriched_at).days
            if days_since < _DOMAIN_HEALTH_TTL_DAYS:
                needs_fetch = False
        except Exception:
            pass

    if needs_fetch:
        new_dr, new_ss, new_ahrefs_dr = fetch_domain_health(domain, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD)
        now_str = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("subscribers").update({
                "domain_rank":        new_dr,
                "spam_score":         new_ss,
                "ahrefs_dr":          new_ahrefs_dr,
                "domain_enriched_at": now_str,
            }).eq("email", email).execute()
        except Exception:
            logging.exception("[domain_health] save fel email=%s", email)
        dr          = new_dr
        ss          = new_ss
        ahrefs_dr   = new_ahrefs_dr
        enriched_at = datetime.now(timezone.utc)

    return {"domain_rank": dr, "spam_score": ss, "ahrefs_dr": ahrefs_dr, "domain_enriched_at": enriched_at}


def _dr_level(dr):
    """Returnerar (etikett, färg) för Domain Rank-nivå."""
    if dr is None:
        return "—", "#6B7280"
    if dr >= 80:
        return "Muito forte", "#16a34a"
    if dr >= 60:
        return "Forte", "#22c55e"
    if dr >= 40:
        return "Consolidado", "#3b82f6"
    if dr >= 20:
        return "Em crescimento", "#f59e0b"
    return "Iniciante", "#6B7280"


def _ahrefs_dr_level(ahrefs_dr):
    """Returnerar (etikett, färg) för Ahrefs Domain Rating-nivå.
    DR=None eller DR=0.0 → 'Sem dados' (Ahrefs saknar backlinkdata för domänen).
    """
    if ahrefs_dr is None or ahrefs_dr == 0.0:
        return "Sem dados", "#6B7280"
    if ahrefs_dr >= 80:
        return "Muito forte", "#16a34a"
    if ahrefs_dr >= 60:
        return "Forte", "#22c55e"
    if ahrefs_dr >= 40:
        return "Consolidado", "#3b82f6"
    if ahrefs_dr >= 20:
        return "Em crescimento", "#f59e0b"
    return "Iniciante", "#6B7280"


def _ss_level(ss):
    """Returnerar (etikett, färg) för Spam Score-nivå."""
    if ss is None:
        return "Não disponível", "#6B7280"
    if ss >= 16:
        return "Alto", "#ef4444"
    if ss >= 6:
        return "Médio", "#f59e0b"
    return "Baixo", "#22c55e"


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


def get_keywords_without_rankings(user_id, domain, access_token=None):
    """
    Returnerar aktiva keywords som saknar RAD i keyword_rankings för domänen.
    En rad = keyword är kontrollerat (oavsett om rank_position är NULL eller ej).
    Används för att bara ranka okontrollerade keywords vid initial ranking (V1).
    """
    logging.info("[get_kwor] start: user=%s domain=%s access_token_present=%s",
                 user_id, domain, bool(access_token))
    try:
        _pg = supabase.postgrest.auth(access_token) if access_token else supabase.postgrest
        all_res = _pg.from_("tracked_keywords") \
            .select("keyword") \
            .eq("user_id", str(user_id)) \
            .eq("is_active", True) \
            .execute()
        all_keywords = {r["keyword"] for r in (all_res.data or [])}
        logging.info("[get_kwor] all_keywords (%d): %s", len(all_keywords), sorted(all_keywords))

        if not all_keywords or not domain:
            logging.info("[get_kwor] returning [] — empty keywords or domain=%r", domain)
            return []

        # Alla keywords med en rad i keyword_rankings räknas som kontrollerade
        # (rank_position=NULL = kontrollerat men ej i topp 100, också klart)
        _pg2 = supabase.postgrest.auth(access_token) if access_token else supabase.postgrest
        ranked_res = _pg2.from_("keyword_rankings") \
            .select("keyword") \
            .eq("user_id", str(user_id)) \
            .eq("domain", domain) \
            .in_("keyword", list(all_keywords)) \
            .execute()
        ranked_keywords = {r["keyword"] for r in (ranked_res.data or [])}
        unranked = sorted(all_keywords - ranked_keywords)
        logging.info("[get_kwor] ranked=%s unranked=%s", sorted(ranked_keywords), unranked)
        return unranked
    except Exception:
        logging.exception("[get_kwor] error: user=%s domain=%s", user_id, domain)
        return []


# ── ON-DEMAND RANKING ─────────────────────────────────────────────────────────

def _fetch_single_rank(keyword, domain, login, password):
    """
    Busca posição de um keyword no Google via DataForSEO (live/advanced).
    Retorna (position, url) ou (None, None) em caso de erro.
    """
    tasks = [{"keyword": keyword, "location_code": 2076, "language_code": "pt", "depth": 100}]
    try:
        r = requests.post(
            "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
            auth=(login, password), json=tasks, timeout=60,
        )
        data = r.json()
    except Exception:
        logging.exception("[dfs_live] kw=%r exception", keyword)
        return None, None

    logging.info("[dfs_live] kw=%r status=%s", keyword, data.get("status_code"))
    if data.get("status_code") != 20000:
        return None, None

    tasks_list = data.get("tasks", [])
    if not tasks_list:
        return None, None

    result = tasks_list[0].get("result") or []
    logging.info("[dfs_live] kw=%r task_status=%s result_len=%d", keyword, tasks_list[0].get("status_code"), len(result))
    if not result:
        return None, None

    items = result[0].get("items", [])
    logging.info("[dfs_live] kw=%r items=%d", keyword, len(items))
    if not items:
        return None, None

    for item in items:
        if item.get("type") != "organic":
            continue
        item_url = item.get("url", "") or ""
        item_domain = item.get("domain", "") or ""
        if domain in item_url or domain in item_domain:
            logging.info("[dfs_match] kw=%r rank=%s url=%r", keyword, item.get("rank_absolute"), item_url)
            return item.get("rank_absolute"), item_url

    return None, None  # Não está no top 100


def run_on_demand_ranking(user_id, domain, keywords, login, password,
                          status_el, progress_bar, access_token=None):
    """
    Verifica posição no Google para todos os keywords com feedback visual.
    Salva em keyword_rankings e retorna (results, save_ok).

    access_token — JWT do usuário autenticado; necessário para RLS em keyword_rankings.
    save_ok=True  → upsert executado E verificação confirmou linhas gravadas.
    save_ok=False → dados buscados mas falha ao salvar.
    """
    logging.info("[rank_fn] user=%s domain=%s keywords=%d", user_id, domain, len(keywords))
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
            "market": "br",
        }
        for kw, d in results.items()
    ]

    save_ok = False
    if rows:
        expected_kws = [r["keyword"] for r in rows]
        try:
            _pg = supabase.postgrest.auth(access_token) if access_token else supabase.postgrest
            logging.info("[on_demand_ranking] upsert: count=%d authenticated=%s",
                         len(rows), bool(access_token))
            _pg.from_("keyword_rankings").upsert(
                rows, on_conflict="user_id,keyword,domain"
            ).execute()
            # Verifiera att raderna faktiskt sparades
            _pg_v = supabase.postgrest.auth(access_token) if access_token else supabase.postgrest
            _verify = (
                _pg_v.from_("keyword_rankings")
                .select("keyword")
                .eq("user_id", str(user_id))
                .eq("domain", domain)
                .in_("keyword", expected_kws)
                .execute()
            )
            found_kws = {r["keyword"] for r in (_verify.data or [])}
            save_ok = set(expected_kws) == found_kws
            logging.info("[on_demand_ranking] verification: expected=%s found=%s save_ok=%s",
                         sorted(expected_kws), sorted(found_kws), save_ok)
        except Exception:
            logging.exception("[on_demand_ranking] upsert error: user=%s domain=%s",
                              user_id, domain)

    return results, save_ok


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


# --- Google Ads Tag (AW-18394590355) ---
st.html("""
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=AW-18394590355"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'AW-18394590355');
</script>
""", unsafe_allow_javascript=True)

# --- Google Ads Conversion Event (Registrering) ---
if st.session_state.get('_gads_conv'):
    st.session_state['_gads_conv'] = False
    st.html("""
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('event', 'conversion', {
    'send_to': 'AW-18394590355/nCq3CIzc1vYcEJPZnMNE',
    'value': 1.0,
    'currency': 'SEK'
  });
</script>
""", unsafe_allow_javascript=True)

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
    html { scroll-behavior: smooth; }
    .garantia {
        font-size: 0.85rem;
        opacity: 0.6;
        margin-top: 0.5rem;
    }
    .social-proof-bar {
        display: flex;
        justify-content: center;
        gap: 1.2rem;
        flex-wrap: wrap;
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 0.85rem 1.5rem;
        margin: 0 auto 1.5rem auto;
        max-width: 660px;
        font-size: 0.88rem;
    }
    .social-proof-bar span {
        color: #cbd5e1;
        display: flex;
        align-items: center;
        gap: 0.35rem;
    }
    .social-proof-bar strong {
        color: #93c5fd;
        font-weight: 700;
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
        background: rgba(26,109,224,0.08);
        border: 2px solid rgba(26,109,224,0.35);
        border-radius: 16px;
        padding: 2.2rem 2rem;
        max-width: 380px;
        margin: 0 auto 2rem auto;
    }
    .price-box .trial-pill {
        display: inline-block;
        background: rgba(74,222,128,0.12);
        color: #4ade80;
        font-size: 0.78rem;
        font-weight: 700;
        padding: 0.25rem 0.8rem;
        border-radius: 999px;
        margin-bottom: 0.9rem;
        letter-spacing: 0.3px;
        text-transform: uppercase;
    }
    .price-box .price { font-size: 2.6rem; font-weight: 800; color: #93c5fd; line-height: 1; }
    .price-box .per { font-size: 0.85rem; opacity: 0.55; margin-bottom: 1.4rem; margin-top: 0.2rem; }
    .price-box ul { list-style: none; padding: 0; margin: 0 0 1.6rem 0; text-align: left; }
    .price-box ul li {
        padding: 0.5rem 0;
        font-size: 0.9rem;
        border-bottom: 1px solid rgba(255,255,255,0.07);
        display: flex;
        gap: 0.5rem;
        align-items: flex-start;
    }
    .price-box ul li:last-child { border-bottom: none; }
    .price-box .no-cc { font-size: 0.78rem; opacity: 0.5; margin-top: 0.75rem; }
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
        <a class="cta-btn" href="#comecar">Comece grátis por 14 dias →</a>
        <div class="garantia">Sem cartão de crédito • Cancele quando quiser</div>
        <div style="margin-top:1.2rem;font-size:0.9rem;opacity:0.65">
            Já tem uma conta?
            <a href="#login-section"
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
    st.markdown('<div class="section-title">Plano único, sem surpresas</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="price-box">
        <div class="trial-pill">14 dias grátis para testar</div>
        <div class="price">R$197</div>
        <div class="per">por mês • sem fidelidade</div>
        <ul>
            <li>🔍 Pesquisa de palavras-chave — até 10 por busca</li>
            <li>✅ Monitoramento de até 100 palavras-chave</li>
            <li>📈 Monitoramento de ranking — até 100 palavras-chave</li>
            <li>📬 Relatório automático toda segunda-feira</li>
            <li>🇧🇷 Dados focados no mercado brasileiro</li>
            <li>📊 Exportação CSV dos resultados</li>
            <li>✉️ Suporte por e-mail</li>
        </ul>
        <a class="cta-btn" href="{HOTMART_URL}">Começar grátis por 14 dias →</a>
        <div class="no-cc">Sem cartão de crédito no período de teste</div>
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
        # Domain Opportunities — isolerad session state
        if "opps_results" not in st.session_state:
            st.session_state.opps_results = None
        if "opps_last_filters" not in st.session_state:
            st.session_state.opps_last_filters = {}

        # --- Onboarding-banner: visa om ingen domän är satt ---
        _ob_email = st.session_state.user.email
        _ob_domain = get_user_domain(_ob_email, st.session_state.access_token)

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

        tab1, tab2, tab3 = st.tabs(["🔍 Pesquisa de palavras-chave", "📈 Meu Monitoramento", "🔎 Oportunidades de Domínios"])

        # ── TAB 1: SÖKNING ──────────────────────────────
        with tab1:

            # ── ON-DEMAND INITIAL RANKING ─────────────────
            if st.session_state.ranking_in_progress:
                _rank_domain = _ob_domain
                _rank_kws = st.session_state._ranking_kws
                logging.info("[rank_block] domain=%s kws_count=%d", _rank_domain, len(_rank_kws) if _rank_kws else 0)
                if _rank_domain and _rank_kws:
                    st.markdown(
                        "<div style='font-weight:700;font-size:1rem;margin-bottom:0.5rem'>"
                        "🔍 Verificando suas posições no Google...</div>",
                        unsafe_allow_html=True,
                    )
                    _status_el = st.empty()
                    _progress_bar = st.progress(0)
                    log_event(user_id, "initial_ranking_started", {"keyword_count": len(_rank_kws)})
                    _ranking_results, _save_ok = run_on_demand_ranking(
                        user_id, _rank_domain, _rank_kws,
                        DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
                        _status_el, _progress_bar,
                        access_token=st.session_state.access_token,
                    )
                    log_event(user_id, "initial_ranking_completed",
                              {"results": {k: v["position"] for k, v in _ranking_results.items()},
                               "save_ok": _save_ok})
                    st.session_state.ranking_in_progress = False
                    st.session_state.ranking_done = _save_ok
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
                    kd = item.get("keyword_difficulty")
                    volume_fmt = f"{int(volume):,}".replace(",", ".")
                    cpc_fmt = f"{float(cpc):.2f}" if cpc else "N/A"
                    kd_str = str(kd) if kd is not None else "—"

                    csv_rows.append({
                        "Palavra-chave": kw,
                        "Volume/mês": volume_fmt,
                        "Dificuldade SEO": kd_str,
                        "Competição Ads": comp,
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
                                <span style="color:#6B7280;font-size:11px">Dificuldade SEO </span>{kd_str}
                            </span>
                            <span style="color:#9CA3AF;font-size:13px">
                                <span style="color:#6B7280;font-size:11px">Comp. Ads </span>{comp}
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
                                    _user_domain = _ob_domain
                                    if _user_domain:
                                        _new_kws = get_keywords_without_rankings(
                                            user_id, _user_domain,
                                            st.session_state.access_token)
                                        if _new_kws:
                                            st.session_state._ranking_kws = _new_kws
                                            st.session_state.ranking_in_progress = True
                                            st.session_state.ranking_done = False
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

                    def _ads_competition_label(cpc):
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
                        ikd      = idea.get("keyword_difficulty")
                        ivol_fmt = f"{int(ivol):,}".replace(",", ".")
                        icpc_fmt = f"{float(icpc):.2f}" if icpc else "N/A"
                        ikd_str  = str(ikd) if ikd is not None else "—"
                        is_opp   = _is_opportunity(idea)
                        diff_label, diff_color = _ads_competition_label(icpc)
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
                                    <span style="color:#6B7280;font-size:11px">Dificuldade SEO </span>{ikd_str}
                                </span>
                                <span style="color:#9CA3AF;font-size:13px">
                                    <span style="color:#6B7280;font-size:11px">Concorrência Ads </span>
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
                                        _user_domain = _ob_domain
                                        if _user_domain:
                                            _new_kws = get_keywords_without_rankings(
                                                user_id, _user_domain,
                                                st.session_state.access_token)
                                            if _new_kws:
                                                st.session_state._ranking_kws = _new_kws
                                                st.session_state.ranking_in_progress = True
                                                st.session_state.ranking_done = False
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
                        supabase.table("subscribers").update({
                            "domain": None,
                            "domain_rank": None,
                            "spam_score": None,
                            "ahrefs_dr": None,
                            "domain_enriched_at": None,
                        }).eq("email", user_email).execute()
                        st.rerun()

            # ── DOMAIN HEALTH CARD ────────────────────────────────────────
            if domain:
                with st.spinner("Carregando autoridade do domínio..."):
                    _health = get_domain_health(user_email, domain)

                if _health is not None:
                    _dr          = _health["domain_rank"]
                    _ss          = _health["spam_score"]
                    _ahrefs_dr   = _health["ahrefs_dr"]
                    _enriched_at = _health["domain_enriched_at"]

                    # Formatering — DataForSEO Domain Rank
                    _dr_display = str(_dr) if _dr is not None else "—"
                    _dr_pct     = _dr if _dr is not None else 0
                    _dr_label, _dr_color = _dr_level(_dr)

                    # Formatering — Spam Score
                    _ss_display = str(_ss) if _ss is not None else "—"
                    _ss_label, _ss_color = _ss_level(_ss)

                    # Formatering — Ahrefs Domain Rating
                    _ahrefs_dr_no_data = (_ahrefs_dr is None or _ahrefs_dr == 0.0)
                    _ahrefs_dr_display = "—" if _ahrefs_dr_no_data else str(int(_ahrefs_dr))
                    _ahrefs_dr_pct     = 0 if _ahrefs_dr_no_data else int(_ahrefs_dr)
                    _ahrefs_dr_label, _ahrefs_dr_color = _ahrefs_dr_level(_ahrefs_dr)

                    _date_str = (
                        _enriched_at.strftime("%-d %b %Y")
                        if _enriched_at else "—"
                    )

                    st.markdown(f"""
                    <div style="background:#1a1a2e;border:1px solid #2d2d4e;border-radius:10px;
                                padding:14px 18px;margin:8px 0 4px 0">
                        <div style="font-size:0.72rem;color:#6B7280;font-weight:600;
                                    letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px">
                            📊 Autoridade do domínio
                        </div>
                        <div style="display:flex;align-items:stretch;gap:0;flex-wrap:wrap">
                            <div style="flex:1;min-width:110px;padding-right:18px">
                                <div style="font-size:0.78rem;color:#9CA3AF;margin-bottom:4px">
                                    Domain Rating
                                    <span style="background:#1e2a3a;color:#818cf8;border:1px solid #3b4070;
                                                 font-size:0.62rem;font-weight:600;padding:1px 6px;
                                                 border-radius:4px;margin-left:5px;vertical-align:middle">novo</span>
                                </div>
                                <div style="font-size:2rem;font-weight:800;color:{'#4B5563' if _ahrefs_dr_no_data else 'white'};line-height:1">{_ahrefs_dr_display}</div>
                                <div style="background:#2d2d4e;border-radius:4px;height:4px;margin:8px 0 5px 0;overflow:hidden">
                                    <div style="background:#6366f1;height:100%;width:{_ahrefs_dr_pct}%;border-radius:4px;transition:width 0.4s"></div>
                                </div>
                                <div style="font-size:0.8rem;color:{_ahrefs_dr_color}">{_ahrefs_dr_label}</div>
                                <div style="font-size:0.7rem;color:#4B5563;margin-top:3px">
                                    <a href="https://ahrefs.com/" target="_blank"
                                       style="color:#6366f1;text-decoration:none">Ahrefs</a>
                                </div>
                            </div>
                            <div style="width:1px;background:#2d2d4e;margin:0 18px 0 0;flex-shrink:0"></div>
                            <div style="flex:1;min-width:110px;padding-right:18px">
                                <div style="font-size:0.78rem;color:#9CA3AF;margin-bottom:4px">Domain Rank</div>
                                <div style="font-size:2rem;font-weight:800;color:white;line-height:1">{_dr_display}</div>
                                <div style="background:#2d2d4e;border-radius:4px;height:4px;margin:8px 0 5px 0;overflow:hidden">
                                    <div style="background:#3b82f6;height:100%;width:{_dr_pct}%;border-radius:4px;transition:width 0.4s"></div>
                                </div>
                                <div style="font-size:0.8rem;color:{_dr_color}">{_dr_label}</div>
                                <div style="font-size:0.7rem;color:#4B5563;margin-top:3px">DataForSEO</div>
                            </div>
                            <div style="width:1px;background:#2d2d4e;margin:0 18px 0 0;flex-shrink:0"></div>
                            <div style="flex:1;min-width:110px">
                                <div style="font-size:0.78rem;color:#9CA3AF;margin-bottom:4px">Spam Score</div>
                                <div style="font-size:2rem;font-weight:800;color:white;line-height:1">{_ss_display}</div>
                                <div style="height:4px;margin:8px 0 5px 0"></div>
                                <div style="font-size:0.8rem;color:{_ss_color}">{_ss_label}</div>
                                <div style="font-size:0.7rem;color:#4B5563;margin-top:3px">DataForSEO</div>
                            </div>
                        </div>
                        <div style="margin-top:12px;padding-top:10px;border-top:1px solid #2d2d4e;
                                    display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
                            <div style="font-size:0.7rem;color:#4B5563">
                                <a href="https://ahrefs.com/" target="_blank"
                                   style="color:#6366f1;text-decoration:none">Domain Rating by Ahrefs</a>
                            </div>
                            <div style="font-size:0.7rem;color:#4B5563">
                                Atualizado em {_date_str}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # DR=0 (DataForSEO): hjälptext
                    if _dr == 0:
                        st.caption("ℹ️ Domain Rank 0 indica que o DataForSEO ainda não registrou backlinks para este domínio. Domínios novos normalmente levam algumas semanas para aparecer.")

                    # Ahrefs DR sem dados: hjälptext
                    if _ahrefs_dr_no_data:
                        st.caption("ℹ️ Domain Rating não disponível — o Ahrefs ainda não registrou backlinks para este domínio. Novos domínios podem levar algumas semanas para aparecer.")

                    # SS médio/alto: varningsinformation
                    if _ss is not None and _ss >= 6:
                        st.caption("ℹ️ Vale a pena revisar o perfil de backlinks para identificar links de baixa qualidade ou potencialmente problemáticos.")

                    # Info om vad värdena betyder
                    with st.expander("O que são Domain Rating, Domain Rank e Spam Score?", expanded=False):
                        st.markdown(
                            "**Domain Rating (Ahrefs)** mede a força do perfil de backlinks em relação a todos os sites "
                            "do índice do Ahrefs, numa escala de 0 a 100. Quanto maior, mais links de qualidade apontam "
                            "para o domínio.\n\n"
                            "**Domain Rank (DataForSEO)** mede a autoridade de backlinks pelo índice do DataForSEO, "
                            "numa escala de 0 a 100. Métrica complementar ao Domain Rating.\n\n"
                            "**Spam Score** indica a probabilidade de o perfil de backlinks conter links de baixa qualidade. "
                            "Valores mais baixos são melhores. Acima de 6%, vale revisar o perfil de links."
                        )

                    # Manuell refresh-knapp (throttlad)
                    _throttle_ok = True
                    if _enriched_at:
                        _days_since = (datetime.now(timezone.utc) - _enriched_at).days
                        _throttle_ok = _days_since >= _DOMAIN_HEALTH_THROTTLE_DAYS

                    if st.button(
                        "Atualizar autoridade",
                        key="refresh_domain_health",
                        disabled=not _throttle_ok,
                        help="Disponível após 7 dias da última atualização" if not _throttle_ok else None,
                    ):
                        with st.spinner("Atualizando..."):
                            _new_dr, _new_ss, _new_ahrefs_dr = fetch_domain_health(
                                domain, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
                            )
                            _now_str = datetime.now(timezone.utc).isoformat()
                            try:
                                supabase.table("subscribers").update({
                                    "domain_rank":        _new_dr,
                                    "spam_score":         _new_ss,
                                    "ahrefs_dr":          _new_ahrefs_dr,
                                    "domain_enriched_at": _now_str,
                                }).eq("email", user_email).execute()
                            except Exception:
                                pass
                        st.rerun()
            # ── /DOMAIN HEALTH CARD ───────────────────────────────────────

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
                st.caption(f"{count}/100 palavras rastreadas — dados atualizados toda segunda-feira")
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

        # ── TAB 3: OPORTUNIDADES DE DOMÍNIOS ─────────────────
        with tab3:
            st.markdown("#### Oportunidades de domínios .com.br")
            st.caption(
                "⚠️ **Disponibilidade não verificada automaticamente.** "
                "Confirme sempre em [Registro.br](https://registro.br/pesquisa-dominio/) "
                "antes de tentar registrar o domínio."
            )

            # Filtros
            with st.expander("⚙️ Filtros de busca", expanded=True):
                _fc1, _fc2, _fc3, _fc4 = st.columns(4)
                with _fc1:
                    _opps_tf_min = st.slider("TF mínimo", 5, 50, 15, key="opps_tf_min",
                                             help="Trust Flow (Majestic). Fonte: CatchDoms")
                with _fc2:
                    _opps_rd_min = st.slider("Referring Domains mín.", 5, 200, 15, key="opps_rd_min",
                                             help="Domínios de referência únicos. Fonte: CatchDoms")
                with _fc3:
                    _opps_score_min = st.slider("Score mínimo", 20, 80, 45, key="opps_score_min",
                                                help="Pontuação geral CatchDoms (0–100)")
                with _fc4:
                    _opps_age_min = st.slider("Idade mínima (anos)", 0, 20, 0, key="opps_age_min",
                                              help="Baseado no primeiro snapshot Wayback")
                _opps_cats = st.multiselect(
                    "Categoria Majestic (opcional)",
                    MAJESTIC_CATEGORIES,
                    key="opps_categories",
                    help="Deixe vazio para todas as categorias"
                )
                _col_btn, _col_reset = st.columns([4, 1])
                with _col_btn:
                    _opps_search = st.button("🔍 Buscar Domínios", key="opps_search_btn", type="primary",
                                             use_container_width=True)
                with _col_reset:
                    if st.session_state.opps_results is not None:
                        if st.button("🔄", key="opps_reset_btn", help="Limpar resultados",
                                     use_container_width=True):
                            st.session_state.opps_results = None
                            st.rerun()

            # Execução da busca
            if _opps_search:
                if not CATCHDOMS_TOKEN:
                    st.error(
                        "CATCHDOMS_TOKEN não configurado. "
                        "Adicione o segredo `CATCHDOMS_TOKEN` nas configurações do Streamlit Cloud."
                    )
                else:
                    _opps_filters = {
                        "tf_min": _opps_tf_min,
                        "rd_min": _opps_rd_min,
                        "score_min": _opps_score_min,
                        "age_min": _opps_age_min,
                        "categories": _opps_cats,
                    }
                    with st.spinner("Buscando domínios em CatchDoms..."):
                        _opps_cd = fetch_catchdoms(
                            tf_min=_opps_tf_min,
                            rd_min=_opps_rd_min,
                            score_min=_opps_score_min,
                            age_min=_opps_age_min,
                            categories=_opps_cats,
                            per_page=25,
                            token=CATCHDOMS_TOKEN,
                        )

                    if isinstance(_opps_cd, dict) and _opps_cd.get("error"):
                        st.error(_opps_cd.get("message", "Erro ao buscar domínios."))
                        st.session_state.opps_results = None
                    elif not _opps_cd:
                        st.info("Nenhum domínio encontrado com esses filtros. Tente reduzir os valores mínimos.")
                        st.session_state.opps_results = []
                    else:
                        _opps_targets = [_d.get("name", "") for _d in _opps_cd if _d.get("name")]
                        with st.spinner(f"Enriquecendo {len(_opps_targets)} domínio(s) com DataForSEO..."):
                            _opps_dfs = enrich_with_dataforseo(
                                _opps_targets, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
                            )
                        st.session_state.opps_results = merge_results(_opps_cd, _opps_dfs)
                        st.session_state.opps_last_filters = _opps_filters

            # Exibição de resultados
            if st.session_state.opps_results is None:
                st.info("Configure os filtros acima e clique em **Buscar Domínios** para encontrar oportunidades.")
            elif len(st.session_state.opps_results) == 0:
                st.info("Nenhum resultado para os filtros selecionados.")
            else:
                _opps_res = st.session_state.opps_results
                st.markdown(f"**{len(_opps_res)} domínio(s) encontrado(s)**")

                # Ordenação
                _opps_sort = st.selectbox(
                    "Ordenar por", ["Score ↓", "TF ↓", "RD ↓", "DR ↓"],
                    key="opps_sort_by", label_visibility="collapsed"
                )
                _sort_field_map = {
                    "Score ↓": "score", "TF ↓": "trust_flow",
                    "RD ↓": "referring_domains", "DR ↓": "dr",
                }
                _sort_field = _sort_field_map[_opps_sort]
                _opps_sorted = sorted(
                    _opps_res,
                    key=lambda x: (x.get(_sort_field) is not None, x.get(_sort_field) or 0),
                    reverse=True,
                )

                # Tabela resumida
                _opps_table = []
                for _d in _opps_sorted:
                    _tf = _d.get("trust_flow")
                    _cf = _d.get("citation_flow")
                    _opps_table.append({
                        "Domínio": _d.get("name", ""),
                        "TF": _tf if _tf is not None else "—",
                        "CF": _cf if _cf is not None else "—",
                        "TF/CF %": tf_cf_ratio(_tf, _cf) or "—",
                        "RD": _d.get("referring_domains") if _d.get("referring_domains") is not None else "—",
                        "Backlinks": compact_num(_d.get("backlinks_count")),
                        "Idade": f"{_d['age']}a" if _d.get("age") is not None else "—",
                        "Score": _d.get("score") if _d.get("score") is not None else "—",
                        "WB": compact_num(_d.get("wayback_snapshots")),
                        "Tráfego": compact_num(_d.get("historical_traffic_peak")),
                        "Categoria": (_d.get("ttf_topic") or _d.get("seo_domains_category") or "—")[:20],
                        "DR": _d.get("dr") if _d.get("dr") is not None else "—",
                        "SS": _d.get("ss") if _d.get("ss") is not None else "—",
                        "⚠️Spam": "Sim" if _d.get("is_spammy") else "Não",
                    })
                _opps_df = pd.DataFrame(_opps_table)
                st.dataframe(_opps_df, use_container_width=True, hide_index=True)

                # Seleção para detalhe
                _opps_names = [_d.get("name", "") for _d in _opps_sorted]
                _opps_detail_sel = st.selectbox(
                    "Ver detalhes de domínio:",
                    _opps_names,
                    key="opps_detail_select",
                )
                _opps_detail_dom = next(
                    (_d for _d in _opps_sorted if _d.get("name") == _opps_detail_sel), None
                )

                if _opps_detail_dom:
                    _dn = _opps_detail_dom
                    _d_tf = _dn.get("trust_flow")
                    _d_cf = _dn.get("citation_flow")
                    _d_rd = _dn.get("referring_domains")
                    _d_bl = _dn.get("backlinks_count")
                    _d_dr = _dn.get("dr")
                    _d_ss = _dn.get("ss")
                    _d_age = _dn.get("age")
                    _d_wb = _dn.get("wayback_snapshots")
                    _d_wb_last = _dn.get("wayback_last_date", "")
                    _d_traffic = _dn.get("historical_traffic_peak")
                    _d_cat = _dn.get("ttf_topic") or _dn.get("seo_domains_category") or "—"
                    _d_lang = _dn.get("language", "—")
                    _d_gmb = _dn.get("has_gmb")
                    _d_price = _dn.get("price")
                    _d_currency = _dn.get("currency", "€")
                    _d_spammy = _dn.get("is_spammy", False)
                    _d_edu = _dn.get("ref_domains_edu")
                    _d_gov = _dn.get("ref_domains_gov")
                    _d_whois = _dn.get("whois_registered_at", "")

                    _d_ratio = tf_cf_ratio(_d_tf, _d_cf)

                    # BL/RD-ratio varning (hög = potentiellt widget/footer-links)
                    _blrd_warn = ""
                    if _d_bl and _d_rd and _d_rd > 0:
                        _blrd = _d_bl / _d_rd
                        if _blrd > 200:
                            _blrd_warn = f"⚠️ BL/RD-ratio hög ({_blrd:.0f}x) — granska o perfil de links manualmente."

                    st.markdown(f"---\n#### 🔍 {_opps_detail_sel}")

                    _det_c1, _det_c2 = st.columns(2)

                    with _det_c1:
                        st.markdown("**🏛️ Autoridade** *(fonte: CatchDoms/DataForSEO)*")
                        _auth_data = {
                            "Trust Flow (TF)": str(_d_tf) if _d_tf is not None else "—",
                            "Citation Flow (CF)": str(_d_cf) if _d_cf is not None else "—",
                            "TF/CF Ratio": _d_ratio or "—",
                            "Domain Rank (DataForSEO)": str(_d_dr) if _d_dr is not None else "— (não encontrado)",
                        }
                        for _lbl, _val in _auth_data.items():
                            st.markdown(f"- **{_lbl}:** {_val}")

                        st.markdown("**📊 Perfil de links** *(fonte: CatchDoms)*")
                        _link_data = {
                            "Referring Domains": compact_num(_d_rd),
                            "Total Backlinks": compact_num(_d_bl),
                            "EDU": compact_num(_d_edu),
                            "GOV": compact_num(_d_gov),
                        }
                        for _lbl, _val in _link_data.items():
                            st.markdown(f"- **{_lbl}:** {_val}")
                        if _blrd_warn:
                            st.warning(_blrd_warn)

                    with _det_c2:
                        st.markdown("**⏱️ Histórico** *(fonte: CatchDoms)*")
                        _hist_data = {
                            "Idade": f"{_d_age} anos" if _d_age is not None else "—",
                            "Wayback Snapshots": compact_num(_d_wb),
                            "Último WB": _d_wb_last or "—",
                            "Tráfego pico": compact_num(_d_traffic),
                            "Categoria": _d_cat,
                            "Idioma": _d_lang,
                            "Google My Business": "Sim" if _d_gmb else "Não" if _d_gmb is not None else "—",
                        }
                        for _lbl, _val in _hist_data.items():
                            st.markdown(f"- **{_lbl}:** {_val}")

                        st.markdown("**🚨 Risco** *(fonte: DataForSEO/CatchDoms)*")
                        _ss_disp = str(_d_ss) if _d_ss is not None else "— (não disponível)"
                        _ss_flag = " 🔴" if _d_ss is not None and _d_ss >= 50 else (
                            " 🟡" if _d_ss is not None and _d_ss >= 30 else ""
                        )
                        st.markdown(f"- **Spam Score (DataForSEO):** {_ss_disp}{_ss_flag}")
                        st.markdown(f"- **is_spammy (CatchDoms):** {'⚠️ Sim' if _d_spammy else 'Não'}")

                        if _d_price:
                            st.markdown(f"- **Preço CatchDoms:** {_d_currency}{_d_price:.2f} *(verifique registrar via registrador direto)*")

                    # Links externos
                    st.markdown("**🔗 Links externos**")
                    _reg_url = registro_br_url(_opps_detail_sel)
                    _wb_url = wayback_url(_opps_detail_sel)
                    _maj_url = majestic_url(_opps_detail_sel)
                    st.markdown(
                        f"[🌐 Verificar disponibilidade no Registro.br]({_reg_url})  |  "
                        f"[📸 Wayback Machine]({_wb_url})  |  "
                        f"[🔗 Majestic]({_maj_url})"
                    )

                    st.caption(
                        "⚠️ Disponibilidade não verificada automaticamente. "
                        "Confirme sempre no Registro.br antes de tentar registrar o domínio."
                    )

    else:
        st.info("✨ Acesso completo por R$197/mês — relatórios automáticos toda segunda-feira.")
        st.markdown(f'<a href="{HOTMART_URL}" target="_blank"><button style="background:#1a6de0;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:15px;">Assinar agora → R$197/mês</button></a>', unsafe_allow_html=True)

st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro | Suporte: samuel@seobrasil.app")

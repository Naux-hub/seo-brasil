import streamlit as st
import pandas as pd
from supabase import create_client
from keyword_cache import get_keyword_data
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

def save_user_domain(email, domain):
    domain = domain.strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    supabase.table("subscribers").update({"domain": domain}).eq("email", email).execute()

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
        return "📉 Saiu do top 100" if prev else "⏳ Aguardando dados"
    if prev is None:
        return f"#{current} 🆕 Novo"
    diff = prev - current  # positivt = klättrade
    if diff > 0:
        return f"#{current} 📈 +{diff} posições"
    elif diff < 0:
        return f"#{current} 📉 {abs(diff)} posições"
    else:
        return f"#{current} → Estável"

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
    </style>
""", unsafe_allow_html=True)

if "user" not in st.session_state:
    st.session_state.user = None
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

# Sätt JWT på supabase-klienten vid varje rerun
if st.session_state.access_token:
    try:
        supabase.postgrest.auth(st.session_state.access_token)
    except Exception:
        pass
elif st.session_state.user is None:
    # Försök återställa session från cookie
    try:
        at = cookie.get("sb_access_token")
        rt = cookie.get("sb_refresh_token")
        if at and rt:
            res = supabase.auth.set_session(at, rt)
            if res and res.user:
                st.session_state.user = res.user
                st.session_state.access_token = res.session.access_token
                st.session_state.refresh_token = res.session.refresh_token
                supabase.postgrest.auth(st.session_state.access_token)
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
        st.markdown("<div style='font-size:1.3rem;font-weight:800;padding:1rem 0 1.5rem'>SEO Brasil 🌎</div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='text-align:center;padding:2rem 1rem;'>
            <div style='font-size:2.5rem;margin-bottom:1rem;'>🔒</div>
            <h2 style='margin-bottom:0.5rem;'>Seu período de teste de 7 dias terminou!</h2>
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

    # --- Social proof ---
    kw_count = get_social_proof()

    # --- Hero ---
    st.markdown(f"""
    <div class="hero">
        <h1>Descubra o que o Brasil<br>está buscando no Google</h1>
        <p>Pesquise palavras-chave para o mercado brasileiro,
        encontre oportunidades e cresça no digital.</p>
        <div class="social-proof-bar">
            <span>🔍 <strong>+{kw_count:,}</strong> palavras-chave analisadas</span>
            <span>📈 Dados atualizados toda semana</span>
            <span>🇧🇷 Focado no mercado brasileiro</span>
        </div>
        <a class="cta-btn" href="#criar-conta">Começar grátis — 14 dias sem cartão →</a>
        <div class="garantia">✅ 14 dias grátis • Sem cartão de crédito • Cancele quando quiser</div>
    </div>
    """, unsafe_allow_html=True)

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
            <div class="icon">⚡</div>
            <h3>Resultados em segundos</h3>
            <p>Busca rápida com cache inteligente — sem esperar.</p>
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
            <h4>Assine</h4>
            <p>R$197/mês, sem contrato. Cancele quando quiser.</p>
        </div>
        <div class="step">
            <div class="num">2</div>
            <h4>Pesquise</h4>
            <p>Digite até 10 palavras-chave e clique em Buscar.</p>
        </div>
        <div class="step">
            <div class="num">3</div>
            <h4>Analise e exporte</h4>
            <p>Veja volume, CPC e competição. Exporte para CSV.</p>
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
            <li>✅ Dados do mercado brasileiro</li>
            <li>✅ Exportação CSV</li>
            <li>✅ Relatórios semanais no seu e-mail</li>
            <li>✅ 14 dias grátis, sem cartão</li>
            <li>✅ Cancele quando quiser</li>
        </ul>
        <a class="cta-btn" href="#criar-conta">Começar teste grátis →</a>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- Registrering / Login ---
    st.markdown('<div class="section-title" id="criar-conta">Comece seu teste gratuito de 14 dias</div>', unsafe_allow_html=True)
    st.caption("Sem cartão de crédito. Cancele quando quiser.")

    with st.form("login_form"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha", type="password")
        col1, col2 = st.columns(2)
        with col1:
            criar = st.form_submit_button("✅ Criar conta grátis", type="primary")
        with col2:
            entrar = st.form_submit_button("Entrar")

    if entrar:
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": senha})
            st.session_state.user = res.user
            st.session_state.access_token = res.session.access_token
            st.session_state.refresh_token = res.session.refresh_token
            supabase.postgrest.auth(res.session.access_token)
            # Uppdatera last_login för dormant user alerts
            try:
                supabase.table("subscribers").update({"last_login": datetime.now(timezone.utc).isoformat()}).eq("email", email).execute()
            except Exception:
                pass
            # Sätt cookies för persistent session
            try:
                cookie.set("sb_access_token", res.session.access_token, max_age=COOKIE_MAX_AGE)
                cookie.set("sb_refresh_token", res.session.refresh_token, max_age=COOKIE_MAX_AGE)
            except Exception:
                pass
            st.rerun()
        except Exception:
            st.error("E-mail ou senha incorretos.")

    if criar:
        if not email or not senha:
            st.error("Preencha e-mail e senha.")
        elif len(senha) < 6:
            st.error("A senha deve ter pelo menos 6 caracteres.")
        else:
            try:
                res = supabase.auth.sign_up({"email": email, "password": senha})
                if res.user:
                    user_id = str(res.user.id)
                    # Skapa rad i subscribers med trial-status
                    try:
                        supabase.table("subscribers").insert({
                            "email": email,
                            "user_id": user_id,
                            "subscription_status": "trial",
                        }).execute()
                    except Exception:
                        pass  # Raden kan redan finnas
                    # Logga in direkt
                    try:
                        login_res = supabase.auth.sign_in_with_password({"email": email, "password": senha})
                        st.session_state.user = login_res.user
                        st.session_state.access_token = login_res.session.access_token
                        st.session_state.refresh_token = login_res.session.refresh_token
                        supabase.postgrest.auth(login_res.session.access_token)
                        cookie.set("sb_access_token", login_res.session.access_token, max_age=COOKIE_MAX_AGE)
                        cookie.set("sb_refresh_token", login_res.session.refresh_token, max_age=COOKIE_MAX_AGE)
                        st.rerun()
                    except Exception:
                        st.success("✅ Conta criada! Faça login para começar seu teste gratuito de 14 dias.")
                else:
                    st.error("Erro ao criar conta. Tente novamente.")
            except Exception as e:
                err = str(e).lower()
                if "already registered" in err or "already exists" in err:
                    st.error("Este e-mail já está cadastrado. Faça login abaixo.")
                else:
                    st.error("Erro ao criar conta. Tente novamente.")

    with st.expander("Esqueceu a senha?"):
        email_reset = st.text_input("Digite seu e-mail para redefinir a senha", key="reset_email")
        if st.button("Enviar link de redefinição"):
            if email_reset:
                try:
                    supabase.auth.reset_password_for_email(
                        email_reset,
                        options={"redirect_to": "https://seobrasil.app"}
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
    st.divider()

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
                        st.success("✅ Site salvo!")
                        st.rerun()
            st.divider()

        tab1, tab2 = st.tabs(["🔍 Pesquisa de palavras-chave", "📈 Meu Monitoramento"])

        # ── TAB 1: SÖKNING ──────────────────────────────
        with tab1:
            sokord_text = st.text_area(
                "Digite as palavras-chave (uma por linha, máx 10):",
                placeholder="agencia de marketing Sao Paulo\nseo para pequenas empresas\nmarketing digital Brasil",
                height=180
            )

            if st.button("Buscar"):
                sokordslista = [s.strip() for s in sokord_text.split("\n") if s.strip()][:10]
                if not sokordslista:
                    st.warning("Digite ao menos uma palavra-chave.")
                else:
                    with st.spinner(f"Buscando dados para {len(sokordslista)} palavra(s)-chave..."):
                        try:
                            items = get_keyword_data(sokordslista, supabase, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD)
                            st.session_state.search_results = items
                        except Exception:
                            st.error("Erro ao buscar dados. Verifique sua conexão e tente novamente.")
                            st.session_state.search_results = None

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

                    col_info, col_btn = st.columns([8, 1])
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
                            if st.button("+ Rastrear", key=f"track_{kw}"):
                                ok, msg = add_tracking(kw, user_id)
                                if ok:
                                    st.success(f"✅ '{kw}' adicionado ao monitoramento!")
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

        # ── TAB 2: MIN ÖVERVAKNING ───────────────────────
        with tab2:
            user_email = st.session_state.user.email
            domain = get_user_domain(user_email)

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

            # Hantera borttagning via query param (från ✕-knapp i HTML-kortet)
            if "del_kw" in st.query_params:
                kw_to_del = st.query_params.get("del_kw", "")
                if kw_to_del:
                    remove_tracking(kw_to_del, user_id)
                st.query_params.clear()
                st.rerun()

            tracked_list = get_tracked_keywords_list(user_id)

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
                    kw_enc = urlquote(kw)

                    st.markdown(f"""
                    <div style="background:#1e1e1e;border-radius:8px;padding:10px 14px;
                                display:flex;justify-content:space-between;align-items:center;
                                margin-bottom:6px">
                        <span style="color:white;font-size:14px;font-weight:500;
                                     flex:1;margin-right:10px">{kw}</span>
                        <span style="color:#9CA3AF;font-size:13px;
                                     white-space:nowrap;margin-right:12px">{trend}</span>
                        <a href="?del_kw={kw_enc}"
                           style="color:#6B7280;text-decoration:none;font-size:14px;
                                  padding:3px 9px;border:1px solid #444;border-radius:5px;
                                  flex-shrink:0;line-height:1.5">✕</a>
                    </div>
                    """, unsafe_allow_html=True)

    else:
        st.info("✨ Acesso completo por R$197/mês — relatórios automáticos toda segunda-feira.")
        st.markdown(f'<a href="{HOTMART_URL}" target="_blank"><button style="background:#1a6de0;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:15px;">Assinar agora → R$197/mês</button></a>', unsafe_allow_html=True)

st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro | Suporte: samuel@seobrasil.app")

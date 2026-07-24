import streamlit as st
import pandas as pd
from supabase import create_client
from keyword_cache import get_keyword_data

DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = st.secrets["DATAFORSEO_PASSWORD"]
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

HOTMART_URL = "https://pay.hotmart.com/L106736067M"

def ar_prenumerant(email):
    res = supabase.table("subscribers").select("email").eq("email", email).execute()
    return len(res.data) > 0

# --- Global CSS ---
st.markdown("""
    <style>
    #GithubIcon {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden;}

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

# =====================================================
# NÃO LOGADO — Landningssida
# =====================================================
if st.session_state.user is None:

    # --- Hero ---
    st.markdown(f"""
    <div class="hero">
        <h1>Descubra o que o Brasil<br>está buscando no Google</h1>
        <p>Pesquise palavras-chave para o mercado brasileiro,
        encontre oportunidades e cresça no digital.</p>
        <a class="cta-btn" href="{HOTMART_URL}" target="_blank">Começar agora — R$197/mês →</a>
        <div class="garantia">✅ Garantia de 15 dias • Cancele quando quiser</div>
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
            <li>✅ Garantia de 15 dias</li>
            <li>✅ Cancele quando quiser</li>
        </ul>
        <a class="cta-btn" href="{HOTMART_URL}" target="_blank">Assinar agora →</a>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- Login (längre ner) ---
    st.markdown('<div class="section-title">Já é assinante? Entre aqui</div>', unsafe_allow_html=True)

    with st.form("login_form"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha", type="password")
        col1, col2 = st.columns(2)
        with col1:
            entrar = st.form_submit_button("Entrar")
        with col2:
            criar = st.form_submit_button("Criar conta")

    if entrar:
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": senha})
            st.session_state.user = res.user
            st.rerun()
        except Exception:
            st.error("E-mail ou senha incorretos.")

    if criar:
        try:
            res = supabase.auth.sign_up({"email": email, "password": senha})
            st.success("Conta criada! Verifique seu e-mail para confirmar.")
        except Exception:
            st.error("Erro ao criar conta.")

    with st.expander("Esqueceu a senha?"):
        email_reset = st.text_input("Digite seu e-mail para redefinir a senha", key="reset_email")
        if st.button("Enviar link de redefinição"):
            if email_reset:
                try:
                    supabase.auth.reset_password_for_email(
                        email_reset,
                        options={"redirect_to": "https://seo-brasil-rguspxutov8fv2ejcic52b.streamlit.app"}
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

    st.title("SEO Brasil")
    st.write(f"Bem-vindo, {st.session_state.user.email}")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()

    st.divider()

    if prenumerant:
        st.subheader("Pesquisa de palavras-chave")
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
                        if not items:
                            st.warning("Nenhum dado encontrado para as palavras-chave informadas.")
                        else:
                            rows = []
                            for item in items:
                                cpc = item.get("cpc") or 0
                                rows.append({
                                    "Palavra-chave": item.get("keyword", ""),
                                    "Volume/mês": item.get("search_volume") or 0,
                                    "Competição": str(item.get("competition", "N/A")).capitalize(),
                                    "CPC médio (R$)": f"{float(cpc):.2f}" if cpc else "N/A",
                                })
                            df = pd.DataFrame(rows)
                            st.dataframe(df, use_container_width=True)

                            csv = df.to_csv(index=False).encode("utf-8-sig")
                            st.download_button(
                                label="📥 Exportar para CSV",
                                data=csv,
                                file_name="seo_brasil.csv",
                                mime="text/csv",
                            )
                    except Exception:
                        st.error("Erro ao buscar dados. Verifique sua conexão e tente novamente.")
    else:
        st.info("✨ Acesso completo por R$197/mês. Garantia de 15 dias.")
        st.markdown(f'<a href="{HOTMART_URL}" target="_blank"><button style="background:#1a6de0;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:15px;">Assinar agora → R$197/mês</button></a>', unsafe_allow_html=True)

st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro | Suporte: seonativo@gmail.com")

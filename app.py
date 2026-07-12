import streamlit as st
import requests
import stripe
import pandas as pd
from supabase import create_client
 
DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = st.secrets["DATAFORSEO_PASSWORD"]
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
 
def hamta_sokdata(sokordslista):
    url = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
    data = [{"keywords": sokordslista, "location_code": 2076, "language_code": "pt"}]
    svar = requests.post(url, auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD), json=data)
    return svar.json()
 
def skapa_checkout(email):
    stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
    price_id = st.secrets["STRIPE_PRICE_ID"]
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        customer_email=email,
        subscription_data={"trial_period_days": 14},
        success_url="https://seo-brasil-rguspxutov8fv2ejcic52b.streamlit.app?paid=true",
        cancel_url="https://seo-brasil-rguspxutov8fv2ejcic52b.streamlit.app",
    )
    return session.url
 
def ar_prenumerant(email):
    res = supabase.table("subscribers").select("email").eq("email", email).execute()
    return len(res.data) > 0
 
def spara_prenumerant(email):
    if not ar_prenumerant(email):
        supabase.table("subscribers").insert({"email": email}).execute()
 
st.title("SEO Brasil")
 
if "user" not in st.session_state:
    st.session_state.user = None
 
if st.session_state.user is None:
    st.subheader("Entrar / Criar conta")
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
        except Exception as e:
            st.error("E-mail ou senha incorretos.")
    if criar:
        try:
            res = supabase.auth.sign_up({"email": email, "password": senha})
            st.success("Conta criada! Verifique seu e-mail para confirmar.")
        except Exception as e:
            st.error("Erro ao criar conta.")
else:
    params = st.query_params
    if params.get("paid") == "true":
        spara_prenumerant(st.session_state.user.email)
        st.success("Pagamento confirmado! Bem-vindo ao SEO Brasil Pro!")
 
    prenumerant = ar_prenumerant(st.session_state.user.email)
 
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
                    resultat = hamta_sokdata(sokordslista)
                    try:
                        items = resultat["tasks"][0]["result"]
                        rows = []
                        for item in items:
                            cpc = item.get("cpc", 0)
                            rows.append({
                                "Palavra-chave": item.get("keyword", ""),
                                "Volume/mês": item.get("search_volume", 0),
                                "Competição": str(item.get("competition", "N/A")).capitalize(),
                                "CPC médio (R$)": f"{cpc:.2f}" if cpc else "N/A",
                            })
                        df = pd.DataFrame(rows)
                        st.dataframe(df, use_container_width=True)
 
                        csv = df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="📥 Exportar para CSV",
                            data=csv,
                            file_name="seo_brasil.csv",
                            mime="text/csv",
                        )
                    except Exception:
                        st.error("Erro ao processar dados. Tente novamente.")
    else:
        st.info("✨ Experimente grátis por 14 dias — sem cobranças agora.")
        if st.button("Começar teste grátis de 14 dias → R$197/mês após"):
            url = skapa_checkout(st.session_state.user.email)
            st.markdown(f"[Clique aqui para continuar]({url})")
 
st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro")
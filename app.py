import streamlit as st
import requests
import stripe
from supabase import create_client

DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = st.secrets["DATAFORSEO_PASSWORD"]
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def hamta_sokdata(sokord):
    url = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
    data = [{"keywords": [sokord], "location_code": 2076, "language_code": "pt"}]
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
        sokord = st.text_input("Digite uma palavra-chave:", placeholder="ex: agencia de marketing Sao Paulo")
        if st.button("Buscar") and sokord:
            with st.spinner("Buscando dados no Google Brasil..."):
                resultat = hamta_sokdata(sokord)
                try:
                    data = resultat['tasks'][0]['result'][0]
                    volym = data.get('search_volume', 0)
                    konkurrens = data.get('competition', 'N/A')
                    cpc = data.get('cpc', 0)
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Volume / mes", f"{volym:,}".replace(",", "."))
                    col2.metric("Competicao", str(konkurrens).capitalize())
                    col3.metric("CPC medio", f"R$ {cpc:.2f}" if cpc else "N/A")
                    st.success(f"Dados do Google Brasil para: {sokord}")
                except:
                    st.error("Nenhum dado encontrado. Tente outra palavra-chave.")
    else:
        st.info("Assine para acessar a pesquisa de palavras-chave.")
        if st.button("Assinar SEO Brasil Pro - R$197/mes"):
            url = skapa_checkout(st.session_state.user.email)
            st.markdown(f"[Clique aqui para pagar]({url})")

st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro")
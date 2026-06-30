import streamlit as st
import requests

DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = st.secrets["DATAFORSEO_PASSWORD"]

def hamta_sokdata(sokord):
    url = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
    data = [{"keywords": [sokord], "location_code": 2076, "language_code": "pt"}]
    svar = requests.post(url, auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD), json=data)
    return svar.json()

st.title("🔍 SEO Brasil")
st.write("Ferramenta de SEO para o mercado brasileiro")
st.divider()
st.subheader("Pesquisa de palavras-chave")

sokord = st.text_input("Digite uma palavra-chave:", placeholder="ex: agência de marketing São Paulo")

if st.button("Buscar") and sokord:
    with st.spinner("Buscando dados no Google Brasil..."):
        resultat = hamta_sokdata(sokord)
        try:
            data = resultat['tasks'][0]['result'][0]
            volym = data.get('search_volume', 0)
            konkurrens = data.get('competition', 'N/A')
            cpc = data.get('cpc', 0)
            col1, col2, col3 = st.columns(3)
            col1.metric("📊 Volume / mês", f"{volym:,}".replace(",", "."))
            col2.metric("⚔️ Competição", str(konkurrens).capitalize())
            col3.metric("💰 CPC médio", f"R$ {cpc:.2f}" if cpc else "N/A")
            st.success(f"Dados do Google Brasil para: **{sokord}**")
        except Exception as e:
            st.error("Nenhum dado encontrado. Tente outra palavra-chave.")

st.divider()
st.caption("SEO Brasil – Feito para o mercado brasileiro 🇧🇷")
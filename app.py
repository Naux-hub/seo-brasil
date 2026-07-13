import streamlit as st
import requests
import pandas as pd
from supabase import create_client

DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = st.secrets["DATAFORSEO_PASSWORD"]
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

KIWIFY_URL = "https://kiwify.app/AN7nQJo"

def hamta_sokdata(sokordslista):
    url = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
    data = [{"keywords": sokordslista, "location_code": 2076, "language_code": "pt"}]
    svar = requests.post(url, auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD), json=data)
    return svar.json()

def ar_prenumerant(email):
    res = supabase.table("subscribers").select("email").eq("email", email).execute()
    return len(res.data) > 0

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
        except Exception:
            st.error("E-mail ou senha incorretos.")

    if criar:
        try:
            res = supabase.auth.sign_up({"email": email, "password": senha})
            st.success("Conta criada! Verifique seu e-mail para confirmar.")
        except Exception:
            st.error("Erro ao criar conta.")

    st.divider()
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

else:
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
                    try:
                        resultat = hamta_sokdata(sokordslista)
                        items = resultat.get("tasks", [{}])[0].get("result", [])
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
                                    "CPC médio (R$)": f"{cpc:.2f}" if cpc else "N/A",
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
        st.info("✨ Acesso completo por R$197/mês. Garantia de 7 dias.")
        st.link_button("Assinar agora → R$197/mês", KIWIFY_URL)

st.divider()
st.caption("SEO Brasil - Feito para o mercado brasileiro | Suporte: seonativo@gmail.com")

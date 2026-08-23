"""
onboarding.py — Sistema de emails de onboarding, triggers e conversão.
Körs dagligen via GitHub Actions (onboarding_daily.yml, 08:00 UTC).

EMAIL CODES (onboarding_emails.day):
  0   = unsubscribed (opt-out de marketing)
  1   = Dag 1 — Ativação / primeiros passos
  3   = Dag 3 — Valor / por que acompanhar ranking
  5   = Dag 5 — Keyword opportunities
  7   = Dag 7 — Relatório semanal
  13  = Dag 13 — Trial termina amanhã
  14  = Dag 14 — Trial terminou / conversão
  15  = Winback dag 15
  22  = Winback dag 22
  44  = Winback dag 44
  99  = Dormant alert
  101 = Trigger T1 — signup sem keyword (≥24h)
  102 = Trigger T2 — ranking pronto mas não visto

UNSUBSCRIBE:
  Inserir (user_id, day=0) em onboarding_emails para bloquear emails futuros.
  Processo manual até que o endpoint de unsubscribe seja implementado.

DRY_RUN:
  Por padrão DRY_RUN=true — não envia emails reais.
  Para produção: defina DRY_RUN=false no GitHub Actions environment.
"""

import os
import time
import secrets
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ── Configuração ──────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

APP_URL = "https://seobrasil.app"
HOTMART_URL = "https://pay.hotmart.com/L106736067M"
TRIAL_DAYS = 14
UNSUBSCRIBE_EMAIL = "oi@seobrasil.app"

# Edge Function URL byggs från SUPABASE_URL (samma env var som redan finns)
# Exempel: "https://abcxyz.supabase.co" → "https://abcxyz.supabase.co/functions/v1/unsubscribe"
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
UNSUB_BASE_URL = f"{_SUPABASE_URL}/functions/v1/unsubscribe"

# OBS: oi@seobrasil.app kräver DNS-verifiering i Resend innan produktion.
# Verifiera domänen på resend.com/domains innan FROM_EMAIL ändras.
FROM_EMAIL = os.environ.get("FROM_EMAIL", "SEO Brasil <oi@seobrasil.app>")

# DRY_RUN: True = loggar vad som skulle skickas, men skickar inga riktiga emails.
# Sätt DRY_RUN=false i GitHub Actions secrets/vars när redo för produktion.
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"


# ── DB-hjälpfunktioner ────────────────────────────────────────────────────────

def get_all_subscribers():
    """Hämtar alla prenumeranter med alla fält som behövs."""
    res = supabase.table("subscribers") \
        .select("email, user_id, created_at, subscription_status, domain") \
        .execute()
    return res.data or []


def days_since(created_at_str):
    """Räknar antal hela dagar sedan created_at."""
    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - created_at).days


def is_unsubscribed(user_id):
    """Returnerar True om användaren har avregistrerat sig (day=0 i onboarding_emails)."""
    res = supabase.table("onboarding_emails") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("day", 0) \
        .execute()
    return len(res.data) > 0


def already_sent(user_id, code):
    """Returnerar True om email med denna kod redan skickats till användaren."""
    res = supabase.table("onboarding_emails") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("day", code) \
        .execute()
    return len(res.data) > 0


def log_sent(user_id, code):
    """Loggar att email skickats (eller simulerades i DRY_RUN)."""
    supabase.table("onboarding_emails").insert({
        "user_id": user_id,
        "day": code,
    }).execute()


def get_or_create_unsub_token(user_id):
    """
    Returnerar befintlig unsubscribe-token för user_id, eller skapar en ny.
    Token lagras i unsubscribe_tokens (UNIQUE user_id).
    Idempotent: samma token returneras vid varje anrop.
    """
    try:
        res = supabase.table("unsubscribe_tokens") \
            .select("token") \
            .eq("user_id", str(user_id)) \
            .limit(1).execute()
        if res.data:
            return res.data[0]["token"]
        token = secrets.token_urlsafe(32)  # 256-bit, ~43 tecken
        supabase.table("unsubscribe_tokens").insert({
            "token": token,
            "user_id": str(user_id),
        }).execute()
        return token
    except Exception as e:
        print(f"    get_or_create_unsub_token fel: {e}")
        return None


def get_activation_status(user_id, domain):
    """
    Returnerar en dict med användarens aktivationsstatus.
    Gör 3 snabba DB-anrop: tracked_keywords, user_events, keyword_rankings.
    """
    result = {
        "has_domain": bool(domain),
        "has_keyword": False,
        "has_ranking_completed": False,
        "has_ranking_viewed": False,
        "has_any_rankings": False,
    }
    try:
        res = supabase.table("tracked_keywords") \
            .select("id", count="exact") \
            .eq("user_id", str(user_id)) \
            .eq("is_active", True) \
            .limit(1).execute()
        result["has_keyword"] = (res.count or 0) > 0
    except Exception:
        pass
    try:
        res = supabase.table("user_events") \
            .select("event") \
            .eq("user_id", str(user_id)) \
            .in_("event", ["initial_ranking_completed", "ranking_viewed"]) \
            .execute()
        events = {r["event"] for r in (res.data or [])}
        result["has_ranking_completed"] = "initial_ranking_completed" in events
        result["has_ranking_viewed"] = "ranking_viewed" in events
    except Exception:
        pass
    try:
        res = supabase.table("keyword_rankings") \
            .select("user_id", count="exact") \
            .eq("user_id", str(user_id)) \
            .limit(1).execute()
        result["has_any_rankings"] = (res.count or 0) > 0
    except Exception:
        pass
    return result


# ── Email-sändning ────────────────────────────────────────────────────────────

def send_email(to_email, subject, html, code, unsub_url=None):
    """
    Skickar email via Resend. I DRY_RUN-läge loggas bara, inget skickas.
    Returnerar True om lyckat (eller DRY_RUN).
    List-Unsubscribe-header sätts till Edge Function-URL om tillgänglig,
    annars mailto-fallback.
    """
    unsub_header = (
        f"<{unsub_url}>, <mailto:{UNSUBSCRIBE_EMAIL}?subject=cancelar>"
        if unsub_url
        else f"<mailto:{UNSUBSCRIBE_EMAIL}?subject=cancelar>"
    )

    if DRY_RUN:
        print(f"    [DRY_RUN] Skulle skicka kod={code} till {to_email}: {subject}")
        return True

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html,
                "headers": {
                    "List-Unsubscribe": unsub_header,
                },
            },
            timeout=15,
        )
        if response.status_code not in (200, 201):
            print(f"    Resend HTTP {response.status_code}: {response.text[:150]}")
            return False
        return True
    except Exception as e:
        print(f"    send_email exception: {e}")
        return False


# ── Email-mallar — gemensam footer ───────────────────────────────────────────

def _unsub_footer(unsub_url=None):
    link = unsub_url if unsub_url else f"mailto:{UNSUBSCRIBE_EMAIL}?subject=cancelar"
    return f"""
    <p style="color:#555;font-size:12px;text-align:center;margin-top:32px;border-top:1px solid #333;padding-top:16px">
      Você recebeu este e-mail porque tem uma conta no SEO Brasil.<br>
      <a href="{link}" style="color:#888">Cancelar inscrição</a>
    </p>"""


def _email_wrapper(header_title, header_sub, body_html, unsub_url=None):
    """Wrapper HTML comum a todos os emails."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#1a1a1a;border-radius:12px;overflow:hidden">
        <tr>
          <td style="background:#1a6de0;padding:28px 32px">
            <h1 style="margin:0;color:white;font-size:22px">{header_title}</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px">{header_sub}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px">
            {body_html}
            {_unsub_footer(unsub_url)}
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _cta_button(text, url):
    return f"""
    <div style="text-align:center;margin:28px 0">
      <a href="{url}" style="display:inline-block;background:#1a6de0;color:white;
         text-decoration:none;padding:14px 32px;border-radius:8px;
         font-weight:bold;font-size:16px">{text}</a>
    </div>"""


# ── Trigger emails ────────────────────────────────────────────────────────────

def email_trigger_t1(email, unsub_url=None):
    """T1 — Signup ≥24h sem nenhuma palavra-chave rastreada."""
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Você criou sua conta no SEO Brasil, mas ainda não adicionou nenhuma palavra-chave para monitorar.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      É simples: pesquise os termos que seus clientes usam no Google e clique em
      <strong style="color:#4d9fff">+ Rastrear</strong>.
      A partir daí, você acompanha sua posição automaticamente toda semana.
    </p>
    <p style="color:#aaa;font-size:14px;line-height:1.6">
      Leva menos de dois minutos para configurar.
    </p>
    {_cta_button("Adicionar minhas palavras-chave →", APP_URL)}
    <p style="color:#555;font-size:13px">Qualquer dúvida, responda este e-mail.<br>Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Vamos acompanhar seu site no Google"
    html = _email_wrapper("Sua conta está pronta 🇧🇷", "Falta um passo para começar", body, unsub_url)
    return subject, html


def email_trigger_t2(email, unsub_url=None):
    """T2 — Ranking concluído mas ranking_viewed ainda não ocorreu."""
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Verificamos as posições do seu site no Google para as palavras-chave que você escolheu.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Seus resultados já estão disponíveis em <strong style="color:white">Meu Monitoramento</strong>.
    </p>
    {_cta_button("Ver meu ranking →", APP_URL)}
    <p style="color:#aaa;font-size:14px;line-height:1.6">
      A partir de agora, seu ranking é atualizado toda segunda-feira de manhã.
    </p>
    <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Seu primeiro ranking está pronto 🚀"
    html = _email_wrapper("Seu ranking está pronto 🚀", "Veja onde você aparece no Google", body, unsub_url)
    return subject, html


# ── Tidsbaserade emails ───────────────────────────────────────────────────────

def email_day1(email, activation, unsub_url=None):
    """Dag 1 — Segmenterat baserat på aktivationsstatus."""
    if activation["has_keyword"]:
        # Användaren har redan lagt till keyword — anpassa innehållet
        body = f"""
        <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Oi! Obrigado por assinar o SEO Brasil. Você já está monitorando suas
          primeiras palavras-chave — ótimo começo.
        </p>
        <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Todo <strong style="color:white">domingo à noite</strong> nosso sistema verifica
          as posições do seu site no Google. Na segunda-feira de manhã você recebe o relatório
          com a evolução de cada palavra-chave.
        </p>
        <p style="color:#aaa;font-size:14px;line-height:1.6">
          Enquanto isso, você pode pesquisar novas palavras e adicionar mais termos ao monitoramento.
        </p>
        {_cta_button("Ver meu monitoramento →", APP_URL)}
        <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>"""
        header_sub = "Sua conta está configurada"
    else:
        # Nenhum keyword ainda — foco em ativação
        body = f"""
        <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Oi! Obrigado por assinar o SEO Brasil.
        </p>
        <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Agora você tem acesso a dados reais de pesquisa do mercado brasileiro — volume de busca,
          CPC e nível de competição, direto do Google Ads.
        </p>
        <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          <strong style="color:white">Comece em 3 passos:</strong>
        </p>
        <ol style="color:#e0e0e0;font-size:15px;line-height:2">
          <li>Acesse a ferramenta e faça login</li>
          <li>Cadastre o endereço do seu site</li>
          <li>Pesquise suas palavras-chave e clique em
              <strong style="color:#1a6de0">+ Rastrear</strong></li>
        </ol>
        {_cta_button("Começar agora →", APP_URL)}
        <p style="color:#555;font-size:13px">Qualquer dúvida, responda este e-mail.<br>Abraço,<br>Samuel — SEO Brasil</p>"""
        header_sub = "Sua conta está pronta"

    subject = "Bem-vindo ao SEO Brasil! 🇧🇷"
    html = _email_wrapper("Bem-vindo ao SEO Brasil! 🇧🇷", header_sub, body, unsub_url)
    return subject, html


def email_day3(email, unsub_url=None):
    """Dag 3 — Valor: por que acompanhar posicionamento ao longo do tempo."""
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Saber sua posição no Google hoje é útil. Mas o que realmente importa é a tendência.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Uma página que está subindo semana após semana — mesmo que ainda não esteja na
      primeira posição — está no caminho certo. Uma que está caindo precisa de atenção agora,
      não daqui a três meses.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      É por isso que o SEO Brasil atualiza seus dados toda semana: para que você tome
      decisões com base em tendências reais, não em snapshots isolados.
    </p>
    <p style="color:#aaa;font-size:14px;line-height:1.6">
      Se você ainda não adicionou seu site, é hora de fazer isso para começar a receber
      os relatórios semanais.
    </p>
    {_cta_button("Ver meu monitoramento →", APP_URL)}
    <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Por que acompanhar seu posicionamento toda semana"
    html = _email_wrapper("SEO é tendência, não posição 📈", "Dica de uso", body, unsub_url)
    return subject, html


def email_day5(email, unsub_url=None):
    """Dag 5 — Keyword opportunities."""
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Você está monitorando algumas palavras-chave — mas talvez esteja deixando passar
      oportunidades que seus concorrentes ainda não perceberam.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      No SEO Brasil, quando você pesquisa uma palavra-chave, o sistema mostra
      <strong style="color:white">Sugestões relacionadas</strong>: termos parecidos,
      com volume real e nível de dificuldade.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Fique de olho nos termos marcados com
      <span style="background:#0d2b1a;color:#2ecc71;font-size:12px;padding:2px 6px;
                   border-radius:4px;font-weight:600">🎯 Oportunidade</span>:
      alto volume de busca, baixa concorrência.
    </p>
    {_cta_button("Encontrar novas palavras-chave →", APP_URL)}
    <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Existem palavras-chave que você ainda não está acompanhando"
    html = _email_wrapper("Palavras-chave que você pode estar perdendo 🔍",
                          "Dica de palavras-chave", body, unsub_url)
    return subject, html


def email_day7(email, unsub_url=None):
    """Dag 7 — Veckorapport-guide."""
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Todo domingo à noite o SEO Brasil verifica as posições do seu site no Google.
      Na segunda-feira você recebe o resultado.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Veja como interpretar os dados quando o relatório chegar:
    </p>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 24px">
      <tr style="background:#2a2a2a">
        <td style="padding:12px 14px;color:#4CAF50;font-size:18px;width:40px">📈</td>
        <td style="padding:12px 14px">
          <p style="margin:0;color:white;font-size:14px;font-weight:bold">Subindo</p>
          <p style="margin:4px 0 0;color:#aaa;font-size:13px">Seu conteúdo está ganhando relevância. Continue.</p>
        </td>
      </tr>
      <tr>
        <td style="padding:12px 14px;color:#e53935;font-size:18px">📉</td>
        <td style="padding:12px 14px">
          <p style="margin:0;color:white;font-size:14px;font-weight:bold">Caindo</p>
          <p style="margin:4px 0 0;color:#aaa;font-size:13px">Considere atualizar ou expandir esse conteúdo.</p>
        </td>
      </tr>
      <tr style="background:#2a2a2a">
        <td style="padding:12px 14px;color:#888;font-size:18px">→</td>
        <td style="padding:12px 14px">
          <p style="margin:0;color:white;font-size:14px;font-weight:bold">Estável</p>
          <p style="margin:4px 0 0;color:#aaa;font-size:13px">SEO leva tempo — o que importa é a tendência em 4–8 semanas.</p>
        </td>
      </tr>
    </table>
    {_cta_button("Ver meu monitoramento →", APP_URL)}
    <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Como funciona o relatório semanal do SEO Brasil"
    html = _email_wrapper("Seu relatório chega toda segunda-feira 📊",
                          "Como interpretar os resultados", body, unsub_url)
    return subject, html


def email_day13(email, unsub_url=None):
    """Dag 13 — Trial slutar imorgon."""
    from urllib.parse import quote as url_quote
    hotmart = f"{HOTMART_URL}?email={url_quote(email, safe='')}"
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Seu período de teste gratuito do SEO Brasil termina amanhã.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Para continuar acompanhando seu posicionamento no Google toda semana, renove agora:
    </p>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#1e1e1e;border:1px solid #333;border-radius:8px;
                  margin:20px 0;padding:20px">
      <tr>
        <td style="padding:12px 16px">
          <p style="margin:0 0 12px;color:#e0e0e0;font-size:14px;font-weight:bold">
            O que você mantém com a assinatura:
          </p>
          <p style="margin:6px 0;color:#aaa;font-size:14px">✓ Monitoramento semanal de posições no Google</p>
          <p style="margin:6px 0;color:#aaa;font-size:14px">✓ Até 20 palavras-chave monitoradas</p>
          <p style="margin:6px 0;color:#aaa;font-size:14px">✓ Relatório automático toda segunda-feira</p>
          <p style="margin:6px 0;color:#aaa;font-size:14px">✓ Sugestões de palavras-chave relacionadas</p>
          <p style="margin:20px 0 0;color:#4d9fff;font-size:18px;font-weight:bold">R$197/mês</p>
        </td>
      </tr>
    </table>
    {_cta_button("Continuar com o SEO Brasil →", hotmart)}
    <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Seu teste gratuito termina amanhã"
    html = _email_wrapper("Seu teste gratuito termina amanhã ⏰",
                          "SEO Brasil — aviso de trial", body, unsub_url)
    return subject, html


def email_day14(email, unsub_url=None):
    """Dag 14 — Trial slut / conversão."""
    from urllib.parse import quote as url_quote
    hotmart = f"{HOTMART_URL}?email={url_quote(email, safe='')}"
    body = f"""
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Seu período de teste gratuito do SEO Brasil terminou hoje.
    </p>
    <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
      Se você quiser continuar acompanhando seu posicionamento no Google —
      e receber o relatório toda segunda-feira — a assinatura está disponível por
      <strong style="color:white">R$197/mês</strong>.
    </p>
    <p style="color:#aaa;font-size:14px;line-height:1.6">
      Suas palavras-chave e configurações continuam salvas. É só reativar para retomar de onde parou.
    </p>
    {_cta_button("Continuar agora →", hotmart)}
    <p style="color:#555;font-size:13px">Qualquer dúvida, responda este e-mail.<br>Abraço,<br>Samuel — SEO Brasil</p>"""
    subject = "Seu teste do SEO Brasil terminou"
    html = _email_wrapper("Seu teste terminou 📅", "Continue acompanhando seu crescimento", body, unsub_url)
    return subject, html


# ── Winback-emails (befintliga, oförändrade) ──────────────────────────────────

def email_winback(email, code, unsub_url=None):
    from urllib.parse import quote as url_quote
    hotmart = f"{HOTMART_URL}?email={url_quote(email, safe='')}"

    if code == 15:
        subject = "Você ainda pensa em crescer no Google? 🌎"
        body = f"""<p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Seu período de teste de 14 dias terminou.<br><br>
          Se você ainda quer aparecer no Google e atrair clientes de forma orgânica,
          o plano está disponível por R$197/mês.</p>"""
    elif code == 22:
        subject = "Última chance de retomar seu monitoramento de SEO 📊"
        body = f"""<p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Já faz uma semana desde que seu teste terminou.<br><br>
          Você pode retomar agora e já receber o próximo relatório na segunda-feira.</p>"""
    else:  # 44
        subject = "Ainda dá tempo de começar a crescer no Google 🚀"
        body = f"""<p style="color:#e0e0e0;font-size:15px;line-height:1.6">
          Um mês atrás você testou o SEO Brasil.<br><br>
          Muita coisa pode ter mudado nas buscas do Google desde então.<br>
          O SEO Brasil está aqui quando você estiver pronto.</p>"""

    body += _cta_button("Reativar minha conta — R$197/mês", hotmart)
    body += f'<p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>'
    html = _email_wrapper("SEO Brasil 🌎", "Retome seu monitoramento", body, unsub_url)
    return subject, html


# ── Huvudlogik ────────────────────────────────────────────────────────────────

WINBACK_CODES = [15, 22, 44]

# Tidsbaserade emails: (dag, builder_fn, extra_segmenteringsvillkor)
# Villkor: lambda activation -> bool. Om False: hoppa över detta mail.
TIME_BASED = [
    (1,  email_day1,  lambda a, **_: True),
    (3,  email_day3,  lambda a, **_: a["has_any_rankings"]),
    (5,  email_day5,  lambda a, **_: a["has_keyword"]),
    (7,  email_day7,  lambda a, **_: a["has_keyword"]),
    (13, email_day13, lambda a, status, **_: status != "active"),
    (14, email_day14, lambda a, status, **_: status != "active"),
]


def run():
    mode = "DRY RUN" if DRY_RUN else "PRODUKTION"
    print(f"=== Onboarding kör {datetime.now().strftime('%Y-%m-%d %H:%M')} [{mode}] ===")

    subscribers = get_all_subscribers()
    print(f"Hittade {len(subscribers)} prenumeranter\n")

    for sub in subscribers:
        email   = sub.get("email")
        user_id = sub.get("user_id")
        created = sub.get("created_at")
        status  = sub.get("subscription_status", "trial")
        domain  = sub.get("domain")

        if not user_id or not created:
            print(f"→ {email}: saknar user_id/created_at, hoppar över")
            continue

        age = days_since(created)
        print(f"→ {email} (dag {age}, status: {status})")

        # ── Unsubscribe-check ──────────────────────────────────────
        if is_unsubscribed(user_id):
            print(f"  Avregistrerad, hoppar över")
            continue

        # ── Aktivationsstatus ──────────────────────────────────────
        activation = get_activation_status(user_id, domain)

        # ── Unsubscribe-URL (unik per användare) ──────────────────
        token = get_or_create_unsub_token(user_id)
        unsub_url = f"{UNSUB_BASE_URL}?token={token}" if token else None

        # Lokal flagga — max ett email per användare per körning
        email_sent_this_run = False

        # ── TRIGGER T1: signup + inget keyword + ≥24h ─────────────
        if (age >= 1
                and not activation["has_keyword"]
                and not already_sent(user_id, 101)):
            subject, html = email_trigger_t1(email, unsub_url=unsub_url)
            ok = send_email(email, subject, html, code=101, unsub_url=unsub_url)
            if ok:
                log_sent(user_id, 101)
                print(f"  ✓ T1 skickat (signup utan keyword)")
                email_sent_this_run = True
            else:
                print(f"  ✗ T1 misslyckades")

        # ── TRIGGER T2: ranking klar men ej sedd ──────────────────
        if (not email_sent_this_run
                and activation["has_ranking_completed"]
                and activation["has_any_rankings"]
                and not activation["has_ranking_viewed"]
                and not already_sent(user_id, 102)):
            subject, html = email_trigger_t2(email, unsub_url=unsub_url)
            ok = send_email(email, subject, html, code=102, unsub_url=unsub_url)
            if ok:
                log_sent(user_id, 102)
                print(f"  ✓ T2 skickat (ranking ej sedd)")
                email_sent_this_run = True
            else:
                print(f"  ✗ T2 misslyckades")

        if email_sent_this_run:
            time.sleep(0.4)
            continue

        # ── TIDSBASERADE EMAILS (trial + active) ───────────────────
        if status == "active" or age <= TRIAL_DAYS:
            for day, build_fn, condition in TIME_BASED:
                if age < day:
                    continue
                if already_sent(user_id, day):
                    continue
                # Dag 1 hoppas permanent om T1 (101) redan skickats
                # — samma budskap, undviker dubbla activation-emails
                if day == 1 and already_sent(user_id, 101):
                    print(f"  ○ Dag 1-mail: T1 redan skickat → hoppar")
                    continue
                # Segmenteringsvillkor
                if not condition(activation, status=status):
                    print(f"  ○ Dag {day}-mail: villkor ej uppfyllt, hoppar över")
                    continue

                # Bygg emailet (dag 1 tar activation, övriga tar bara email)
                if day == 1:
                    subject, html = build_fn(email, activation, unsub_url=unsub_url)
                else:
                    subject, html = build_fn(email, unsub_url=unsub_url)

                ok = send_email(email, subject, html, code=day, unsub_url=unsub_url)
                if ok:
                    log_sent(user_id, day)
                    print(f"  ✓ Dag {day}-mail skickat")
                    email_sent_this_run = True
                else:
                    print(f"  ✗ Dag {day}-mail misslyckades")

                break  # Bara ett tidsbaserat email per körning

        else:
            # ── WINBACK (expired trial) ────────────────────────────
            for code in WINBACK_CODES:
                if age >= code and not already_sent(user_id, code):
                    subject, html = email_winback(email, code, unsub_url=unsub_url)
                    ok = send_email(email, subject, html, code=code, unsub_url=unsub_url)
                    if ok:
                        log_sent(user_id, code)
                        print(f"  ✓ Winback {code} skickat")
                        email_sent_this_run = True
                    else:
                        print(f"  ✗ Winback {code} misslyckades")
                    break  # Bara en winback per körning

        if email_sent_this_run:
            time.sleep(0.4)

    print(f"\n=== Onboarding klar [{mode}] ===")


if __name__ == "__main__":
    run()

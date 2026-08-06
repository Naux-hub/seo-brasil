"""
onboarding.py — Skickar onboarding-e-post till nya prenumeranter dag 1, 3 och 7.
Körs dagligen via GitHub Actions.
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# --- Anslutningar ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

FROM_EMAIL = "SEO Brasil <onboarding@resend.dev>"
APP_URL = "https://seobrasil.app"


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def get_all_subscribers():
    """Hämtar email, user_id, created_at och subscription_status för alla prenumeranter."""
    res = supabase.table("subscribers").select("email, user_id, created_at, subscription_status").execute()
    return res.data


def days_since(created_at_str):
    """Räknar antal hela dagar sedan prenumeranten registrerades."""
    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - created_at).days


def already_sent(user_id, day):
    """Kontrollerar om dag-X-mailet redan skickats."""
    res = supabase.table("onboarding_emails") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("day", day) \
        .execute()
    return len(res.data) > 0


def log_sent(user_id, day):
    """Loggar att mailet skickats."""
    supabase.table("onboarding_emails").insert({
        "user_id": user_id,
        "day": day,
    }).execute()


def send_email(to_email, subject, html):
    """Skickar e-post via Resend API. Returnerar False vid fel utan att krascha."""
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
            },
            timeout=15,
        )
        if response.status_code != 200:
            print(f"    Resend HTTP {response.status_code}: {response.text[:120]}")
        return response.status_code == 200
    except Exception as e:
        print(f"    send_email exception: {e}")
        return False


# ---------------------------------------------------------------------------
# E-postmallar (portugisiska)
# ---------------------------------------------------------------------------

def email_day1(email):
    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;overflow:hidden">

        <tr>
          <td style="background:#1a6de0;padding:28px 32px">
            <h1 style="margin:0;color:white;font-size:22px">Bem-vindo ao SEO Brasil! 🇧🇷</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px">Sua conta está pronta</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px">
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">Oi! Obrigado por assinar o SEO Brasil.</p>
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
              Agora você tem acesso a dados reais de pesquisa do mercado brasileiro — volume de busca, CPC e nível de competição, direto do Google Ads.
            </p>

            <p style="color:#e0e0e0;font-size:15px;line-height:1.6"><strong style="color:white">Comece agora em 3 passos:</strong></p>
            <ol style="color:#e0e0e0;font-size:15px;line-height:2">
              <li>Acesse a ferramenta e faça login</li>
              <li>Cadastre o endereço do seu site <span style="color:#aaa;font-size:13px">(para ativar o relatório semanal)</span></li>
              <li>Pesquise suas palavras-chave e clique em <strong style="color:#1a6de0">+ Rastrear</strong></li>
            </ol>

            <p style="color:#aaa;font-size:14px;line-height:1.6">
              A partir de agora, toda segunda-feira você recebe um relatório mostrando como suas posições no Google estão evoluindo.
            </p>

            <div style="text-align:center;margin:28px 0">
              <a href="{APP_URL}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px">
                Acessar o SEO Brasil →
              </a>
            </div>

            <p style="color:#555;font-size:13px">Qualquer dúvida, responda este e-mail.</p>
            <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return "Bem-vindo ao SEO Brasil! Sua conta está pronta 🇧🇷", html


def email_day3(email):
    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;overflow:hidden">

        <tr>
          <td style="background:#1a6de0;padding:28px 32px">
            <h1 style="margin:0;color:white;font-size:22px">Como escolher as palavras certas 🎯</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px">Dica rápida de SEO</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px">
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
              A maioria dos sites tenta rankear para palavras muito genéricas — e perde para grandes portais.
            </p>
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
              A estratégia que funciona para quem está começando é focar em <strong style="color:white">palavras-chave de cauda longa</strong> (long-tail): termos mais específicos, com menos concorrência e volume mais realista.
            </p>

            <p style="color:#e0e0e0;font-size:15px;margin-bottom:8px"><strong style="color:white">Exemplo prático:</strong></p>
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px">
              <tr style="background:#2a2a2a">
                <td style="padding:10px 14px;color:#aaa;font-size:13px">❌ Difícil de rankear</td>
                <td style="padding:10px 14px;color:#e0e0e0;font-size:14px">"seguro de carro"</td>
              </tr>
              <tr>
                <td style="padding:10px 14px;color:#aaa;font-size:13px">✅ Mais fácil</td>
                <td style="padding:10px 14px;color:#4CAF50;font-size:14px">"seguro de carro para motorista de aplicativo em SP"</td>
              </tr>
            </table>

            <p style="color:#aaa;font-size:14px;line-height:1.6">
              No SEO Brasil, filtre por <strong>Competição baixa</strong> e <strong>volume acima de 100</strong> para encontrar essas oportunidades.
            </p>

            <div style="text-align:center;margin:28px 0">
              <a href="{APP_URL}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px">
                Pesquisar palavras agora →
              </a>
            </div>

            <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return "Como escolher as palavras-chave certas para o seu nicho 🎯", html


def email_day7(email):
    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;overflow:hidden">

        <tr>
          <td style="background:#1a6de0;padding:28px 32px">
            <h1 style="margin:0;color:white;font-size:22px">Sua primeira semana de dados 📈</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px">Como interpretar seu relatório</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px">
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
              Na próxima segunda-feira você vai receber seu primeiro relatório semanal de SEO. Veja abaixo como interpretar os resultados quando ele chegar:
            </p>

            <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 24px">
              <tr style="background:#2a2a2a">
                <td style="padding:12px 14px;color:#4CAF50;font-size:18px;width:40px">🟢</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Subindo esta semana</p>
                  <p style="margin:4px 0 0;color:#aaa;font-size:13px">Seu conteúdo está ganhando relevância. Continue publicando sobre esse tema.</p>
                </td>
              </tr>
              <tr>
                <td style="padding:12px 14px;color:#e53935;font-size:18px">🔴</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Precisa da sua atenção</p>
                  <p style="margin:4px 0 0;color:#aaa;font-size:13px">Um concorrente pode ter publicado algo novo. Considere atualizar ou expandir seu conteúdo.</p>
                </td>
              </tr>
              <tr style="background:#2a2a2a">
                <td style="padding:12px 14px;color:#888;font-size:18px">→</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Estável</p>
                  <p style="margin:4px 0 0;color:#aaa;font-size:13px">Posição mantida. SEO leva tempo — resultados aparecem em semanas ou meses.</p>
                </td>
              </tr>
              <tr>
                <td style="padding:12px 14px;color:#f5a623;font-size:18px">🎯</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Foco desta semana</p>
                  <p style="margin:4px 0 0;color:#aaa;font-size:13px">Sua página está entre as posições 11–20. Um pouco mais de esforço pode colocá-la na primeira página do Google.</p>
                </td>
              </tr>
            </table>

            <p style="color:#aaa;font-size:14px;line-height:1.6">
              <strong style="color:white">Dica:</strong> Não se preocupe com variações semanais pequenas. O que importa é a tendência ao longo de 4–8 semanas.
            </p>

            <!-- Novo recurso: monitoramento de domínio -->
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e2d1e;border:1px solid #2e5c2e;border-radius:10px;margin:24px 0">
              <tr>
                <td style="padding:20px 24px">
                  <p style="margin:0 0 8px;color:#4CAF50;font-size:13px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px">✨ Novidade — monitoramento do seu site</p>
                  <p style="margin:0 0 12px;color:#e0e0e0;font-size:15px;line-height:1.6">
                    Agora você pode adicionar o endereço do seu site e acompanhar exatamente em que posição ele aparece no Google — para cada palavra-chave que você rastreia.
                  </p>
                  <p style="margin:0 0 16px;color:#aaa;font-size:14px;line-height:1.5">
                    Vá até a aba <strong style="color:white">Meu Monitoramento</strong>, adicione seu site (ex: <code style="background:#2a2a2a;padding:2px 6px;border-radius:4px;color:#4d9fff">meusite.com.br</code>) e os dados chegam toda segunda-feira.
                  </p>
                  <a href="{APP_URL}" style="display:inline-block;background:#2e5c2e;color:#ffffff;text-decoration:none;padding:10px 20px;border-radius:6px;font-weight:bold;font-size:14px">
                    Adicionar meu site agora →
                  </a>
                </td>
              </tr>
            </table>

            <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return "Sua primeira semana de dados — como interpretar seu relatório 📈", html


# ---------------------------------------------------------------------------
# Winback-mejl (dag 8, 14, 30) — för expired trial-användare
# ---------------------------------------------------------------------------

def email_winback(email, day):
    from urllib.parse import quote as url_quote
    email_enc = url_quote(email, safe="")
    hotmart_url = f"https://pay.hotmart.com/L106736067M?email={email_enc}"

    if day == 15:
        subject = "Você ainda pensa em crescer no Google? 🌎"
        body = f"""<p style="color:#e0e0e0;font-size:15px;line-height:1.6">
            Seu período de teste de 14 dias terminou ontem.<br><br>
            Durante esses 14 dias, você viu de perto como o SEO Brasil funciona — os dados de busca, o monitoramento de posições e o relatório automático toda segunda-feira.<br><br>
            Se você ainda quer aparecer no Google e atrair clientes de forma orgânica, o plano está disponível por R$197/mês — menos do que um dia de anúncio no Meta.
        </p>"""
    elif day == 22:
        subject = "Última chance de retomar seu monitoramento de SEO 📊"
        body = f"""<p style="color:#e0e0e0;font-size:15px;line-height:1.6">
            Já faz uma semana desde que seu teste de 14 dias terminou.<br><br>
            Enquanto isso, seus concorrentes continuam sendo rastreados no Google toda semana.<br><br>
            Você pode retomar agora e já receber o próximo relatório na segunda-feira.
        </p>"""
    else:  # day == 44
        subject = "Ainda dá tempo de começar a crescer no Google 🚀"
        body = f"""<p style="color:#e0e0e0;font-size:15px;line-height:1.6">
            Um mês atrás você testou o SEO Brasil.<br><br>
            Muita coisa pode ter mudado nas buscas do Google desde então — novos concorrentes, novas oportunidades de palavras-chave.<br><br>
            O SEO Brasil está aqui quando você estiver pronto para crescer de forma orgânica.
        </p>"""

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;overflow:hidden">
        <tr><td style="background:#1a6de0;padding:28px 32px">
          <h1 style="margin:0;color:white;font-size:22px">SEO Brasil 🌎</h1>
        </td></tr>
        <tr><td style="padding:32px">
          {body}
          <div style="text-align:center;margin:28px 0">
            <a href="{hotmart_url}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px">
              👉 Reativar minha conta — R$197/mês
            </a>
          </div>
          <p style="color:#9CA3AF;font-size:13px">Dúvidas? Responda este e-mail.<br>Abraço,<br>Samuel — SEO Brasil</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return subject, html


# ---------------------------------------------------------------------------
# Huvudlogik
# ---------------------------------------------------------------------------

ONBOARDING_DAYS = {1: email_day1, 3: email_day3, 7: email_day7}
WINBACK_DAYS = [15, 22, 44]


def run():
    print(f"=== Onboarding kör {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    subscribers = get_all_subscribers()
    print(f"Hittade {len(subscribers)} prenumeranter")

    for sub in subscribers:
        email = sub.get("email")
        user_id = sub.get("user_id")
        created_at = sub.get("created_at")
        status = sub.get("subscription_status", "trial")

        if not user_id or not created_at:
            print(f"  {email}: saknar user_id eller created_at, hoppar över")
            continue

        age = days_since(created_at)
        print(f"\n→ {email} (dag {age}, status: {status})")

        if status == "active" or age <= 14:
            # Onboarding-mejl dag 1, 3, 7
            for day, build_email in ONBOARDING_DAYS.items():
                if age >= day and not already_sent(user_id, day):
                    subject, html = build_email(email)
                    ok = send_email(email, subject, html)
                    if ok:
                        log_sent(user_id, day)
                        print(f"  ✓ Dag {day}-mail skickat")
                        time.sleep(0.4)  # ~2.5 mejl/sek — håller oss under rate limit
                    else:
                        print(f"  ✗ Dag {day}-mail misslyckades")
        else:
            # Winback-mejl dag 8, 14, 30 — bara till expired trials
            for day in WINBACK_DAYS:
                if age >= day and not already_sent(user_id, day):
                    subject, html = email_winback(email, day)
                    ok = send_email(email, subject, html)
                    if ok:
                        log_sent(user_id, day)
                        print(f"  ✓ Winback dag {day}-mail skickat")
                        time.sleep(0.4)
                    else:
                        print(f"  ✗ Winback dag {day}-mail misslyckades")

    print("\n=== Onboarding klar ===")


if __name__ == "__main__":
    run()

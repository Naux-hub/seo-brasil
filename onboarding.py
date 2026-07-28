"""
onboarding.py — Skickar onboarding-e-post till nya prenumeranter dag 1, 3 och 7.
Körs dagligen via GitHub Actions.
"""

import os
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

def get_active_subscribers():
    """Hämtar email, user_id och created_at för alla aktiva prenumeranter."""
    res = supabase.table("subscribers").select("email, user_id, created_at").execute()
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
    """Skickar e-post via Resend API."""
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
    return response.status_code == 200


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
              <li>Pesquise as palavras-chave do seu nicho</li>
              <li>Clique em <strong style="color:#1a6de0">+ Rastrear</strong> nas palavras que mais importam para você</li>
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
              No SEO Brasil, filtre por <strong>KD baixo</strong> (dificuldade de competição) e <strong>volume acima de 100</strong> para encontrar essas oportunidades.
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
              Hoje você recebeu (ou está prestes a receber) seu primeiro relatório semanal de SEO. Veja como interpretar os resultados:
            </p>

            <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 24px">
              <tr style="background:#2a2a2a">
                <td style="padding:12px 14px;color:#4CAF50;font-size:18px;width:40px">📈</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Subindo posições</p>
                  <p style="margin:4px 0 0;color:#aaa;font-size:13px">Seu conteúdo está ganhando relevância. Continue publicando sobre esse tema.</p>
                </td>
              </tr>
              <tr>
                <td style="padding:12px 14px;color:#e53935;font-size:18px">📉</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Descendo posições</p>
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
                <td style="padding:12px 14px;color:#4CAF50;font-size:18px">🆕</td>
                <td style="padding:12px 14px">
                  <p style="margin:0;color:white;font-size:14px;font-weight:bold">Novo no ranking</p>
                  <p style="margin:4px 0 0;color:#aaa;font-size:13px">Sua página entrou no top 100 do Google. Bom sinal!</p>
                </td>
              </tr>
            </table>

            <p style="color:#aaa;font-size:14px;line-height:1.6">
              <strong style="color:white">Dica:</strong> Não se preocupe com variações semanais pequenas. O que importa é a tendência ao longo de 4–8 semanas.
            </p>

            <div style="text-align:center;margin:28px 0">
              <a href="{APP_URL}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px">
                Ver meu monitoramento →
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
    return "Sua primeira semana de dados — como interpretar seu relatório 📈", html


# ---------------------------------------------------------------------------
# Huvudlogik
# ---------------------------------------------------------------------------

EMAIL_DAYS = {1: email_day1, 3: email_day3, 7: email_day7}


def run():
    print(f"=== Onboarding kör {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    subscribers = get_active_subscribers()
    print(f"Hittade {len(subscribers)} prenumeranter")

    for sub in subscribers:
        email = sub.get("email")
        user_id = sub.get("user_id")
        created_at = sub.get("created_at")

        if not user_id or not created_at:
            print(f"  {email}: saknar user_id eller created_at, hoppar över")
            continue

        age = days_since(created_at)
        print(f"\n→ {email} (dag {age})")

        for day, build_email in EMAIL_DAYS.items():
            if age >= day and not already_sent(user_id, day):
                subject, html = build_email(email)
                ok = send_email(email, subject, html)
                if ok:
                    log_sent(user_id, day)
                    print(f"  ✓ Dag {day}-mail skickat")
                else:
                    print(f"  ✗ Dag {day}-mail misslyckades")

    print("\n=== Onboarding klar ===")


if __name__ == "__main__":
    run()

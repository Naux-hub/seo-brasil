"""
dormant_alerts.py — Skickar påminnelsemejl till användare som inte loggat in på 14 dagar.
Körs dagligen via GitHub Actions (samma workflow som onboarding).
"""

import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# --- Anslutningar ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service role key — endast server-side
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

FROM_EMAIL = "SEO Brasil <oi@seobrasil.app>"
APP_URL = "https://seobrasil.app"
DORMANT_DAYS = 14


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def get_dormant_subscribers():
    """Hämtar prenumeranter som inte loggat in på 14+ dagar."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DORMANT_DAYS)).isoformat()
    res = supabase.table("subscribers") \
        .select("email, user_id, last_login") \
        .lt("last_login", cutoff) \
        .execute()
    return res.data


def already_alerted_recently(user_id):
    """Kollar om vi skickat dormant-alert de senaste 30 dagarna (undvik spam)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = supabase.table("onboarding_emails") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("day", 99) \
        .gt("sent_at", cutoff) \
        .execute()
    return len(res.data) > 0


def log_alert_sent(user_id):
    """Loggar dormant-alert som dag 99 i onboarding_emails."""
    supabase.table("onboarding_emails").insert({
        "user_id": user_id,
        "day": 99,
    }).execute()


def send_email(to_email, subject, html):
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
# E-postmall
# ---------------------------------------------------------------------------

def build_dormant_email(email):
    subject = "Suas palavras-chave estão esperando por você 👀"
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
            <h1 style="margin:0;color:white;font-size:22px">Suas palavras-chave estão esperando 👀</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px">SEO Brasil — atualização</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px">
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
              Faz um tempinho que você não acessa o SEO Brasil.
            </p>
            <p style="color:#e0e0e0;font-size:15px;line-height:1.6">
              Enquanto isso, continuamos rastreando suas posições no Google toda semana. Os dados estão lá esperando — pode ser que você já tenha subido algumas posições sem saber. 📈
            </p>

            <div style="background:#2a2a2a;border-radius:8px;padding:20px 24px;margin:24px 0">
              <p style="margin:0;color:#aaa;font-size:13px;text-transform:uppercase;letter-spacing:1px">O que você pode fazer agora</p>
              <ul style="color:#e0e0e0;font-size:15px;line-height:2;margin:12px 0 0;padding-left:20px">
                <li>Ver como suas palavras-chave evoluíram</li>
                <li>Adicionar novas palavras do seu nicho</li>
                <li>Descobrir oportunidades que seus concorrentes ainda não viram</li>
              </ul>
            </div>

            <div style="text-align:center;margin:28px 0">
              <a href="{APP_URL}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px">
                Ver meu monitoramento →
              </a>
            </div>

            <p style="color:#555;font-size:13px">
              Se você não quiser mais receber esses e-mails, responda com "cancelar".
            </p>
            <p style="color:#555;font-size:13px">Abraço,<br>Samuel — SEO Brasil</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return subject, html


# ---------------------------------------------------------------------------
# Huvudlogik
# ---------------------------------------------------------------------------

def run():
    print(f"=== Dormant Alerts kör {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    dormant = get_dormant_subscribers()
    print(f"Hittade {len(dormant)} dormanta prenumeranter (>{DORMANT_DAYS} dagar)")

    for sub in dormant:
        email = sub.get("email")
        user_id = sub.get("user_id")
        last_login = sub.get("last_login", "okänt")

        if not user_id:
            print(f"  {email}: saknar user_id, hoppar över")
            continue

        print(f"\n→ {email} (senaste login: {last_login})")

        if already_alerted_recently(user_id):
            print(f"  Alert skickat nyligen, hoppar över")
            continue

        subject, html = build_dormant_email(email)
        ok = send_email(email, subject, html)
        if ok:
            log_alert_sent(user_id)
            print(f"  ✓ Dormant alert skickat")
        else:
            print(f"  ✗ Misslyckades")

    print("\n=== Dormant Alerts klar ===")


if __name__ == "__main__":
    run()

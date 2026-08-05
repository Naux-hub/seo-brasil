"""
weekly_report.py — Skickar veckovisa rankingrapporter till alla aktiva prenumeranter.
Körs varje måndag via GitHub Actions, efter rank_tracker.py.
"""

import os
import requests
from datetime import datetime, timezone
from urllib.parse import quote as url_quote
from supabase import create_client

# --- Anslutningar ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

FROM_EMAIL = "SEO Brasil <onboarding@resend.dev>"
APP_URL = "https://seobrasil.app"


def get_active_subscribers():
    """Returnerar prenumeranter med aktiv status ELLER trial inom 7 dagar."""
    res = supabase.table("subscribers").select("email, domain, subscription_status, created_at").execute()
    now = datetime.now(timezone.utc)
    active = []
    expired = []
    for row in (res.data or []):
        status = row.get("subscription_status", "trial")
        if status == "active":
            active.append(row)
        else:
            created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            days = (now - created_at).days
            if days <= 14:
                active.append(row)
            else:
                expired.append(row)
    return active, expired


def build_teaser_html(email, domain):
    """Teaser-mejl till trial-expired användare — påminner om vad de missar."""
    email_enc = url_quote(email, safe="")
    hotmart_url = f"https://pay.hotmart.com/L106736067M?email={email_enc}"
    today = datetime.now().strftime("%d/%m/%Y")
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0e1117;font-family:'Helvetica Neue',Arial,sans-serif;color:#e0e0e0">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1a1d24;border-radius:12px;overflow:hidden;max-width:600px">

        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,#1a6de0,#0d47a1);padding:28px 32px;text-align:center">
          <div style="font-size:1.5rem;font-weight:800;color:white;letter-spacing:-0.5px">SEO Brasil 🌎</div>
          <div style="color:rgba(255,255,255,0.8);font-size:0.85rem;margin-top:4px">Relatório da semana — {today}</div>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:32px">
          <p style="margin:0 0 16px;font-size:1rem;color:#ccc;">Olá!</p>
          <p style="margin:0 0 24px;font-size:1rem;color:#ccc;">
            Esta semana atualizamos as posições e o volume de busca das palavras-chave monitoradas para
            <strong style="color:#fff">{domain}</strong>.
          </p>
          <div style="background:#2a2d35;border-left:4px solid #e53935;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
            <div style="font-size:1.1rem;font-weight:700;color:#fff;margin-bottom:8px;">⚠️ Relatório pausado</div>
            <p style="margin:0;color:#aaa;font-size:0.95rem;">
              Como seu período de teste de 14 dias terminou, seu relatório semanal foi pausado.
              Assine para ver quais termos subiram, quais caíram e onde focar esta semana.
            </p>
          </div>
          <div style="text-align:center;margin:32px 0;">
            <a href="{hotmart_url}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px;">
              👉 Reativar minha conta — R$197/mês
            </a>
          </div>
          <p style="text-align:center;color:#555;font-size:12px;margin:0;">
            Dúvidas? Responda este e-mail.<br>
            <a href="https://seobrasil.app" style="color:#555;">seobrasil.app</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def get_user_id_by_email(email):
    res = supabase.table("subscribers").select("user_id").eq("email", email).execute()
    if res.data and res.data[0].get("user_id"):
        return str(res.data[0]["user_id"])
    return None


def get_tracked_keywords(user_id):
    res = supabase.table("tracked_keywords") \
        .select("keyword") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    return [r["keyword"] for r in res.data]


def get_keyword_ranking(user_id, domain, keyword):
    """Hämtar aktuell och föregående position för ett sökord från keyword_rankings."""
    res = supabase.table("keyword_rankings") \
        .select("rank_position, prev_rank_position") \
        .eq("user_id", user_id) \
        .eq("domain", domain) \
        .eq("keyword", keyword) \
        .order("checked_at", desc=True) \
        .limit(1) \
        .execute()
    if res.data:
        return res.data[0]["rank_position"], res.data[0]["prev_rank_position"]
    return None, None


def trend_html(current, previous):
    """Returnerar HTML-sträng med position och trend-pil."""
    if current is None:
        pos_str = "— (fora do top 100)"
        color = "#888"
        arrow = ""
    else:
        pos_str = f"#{current}"
        if previous is None:
            arrow = " <span style='color:#4CAF50'>🆕 Novo</span>"
            color = "#4CAF50"
        else:
            diff = previous - current
            if diff > 0:
                arrow = f" <span style='color:#4CAF50'>▲ +{diff}</span>"
                color = "#4CAF50"
            elif diff < 0:
                arrow = f" <span style='color:#e53935'>▼ {diff}</span>"
                color = "#e53935"
            else:
                arrow = " <span style='color:#888'>→ Estável</span>"
                color = "#888"

    return f"<span style='font-weight:bold;color:{color}'>{pos_str}</span>{arrow}"


def build_email_html(email, keyword_data):
    """Constrói o HTML do e-mail semanal com três seções: Atenção, Subindo e Foco."""
    today = datetime.now().strftime("%d/%m/%Y")
    email_enc = url_quote(email, safe="")
    feedback_up_url = f"{APP_URL}?feedback=up&email={email_enc}"
    feedback_down_url = f"{APP_URL}?feedback=down&email={email_enc}"

    # --- Categorias ---
    attention = [(kw, c, p) for kw, c, p in keyword_data
                 if c is not None and p is not None and (c - p) >= 3]
    wins = [(kw, c, p) for kw, c, p in keyword_data
            if c is not None and p is not None and c < p]
    wins_kws = {kw for kw, _, _ in wins}
    focus = [(kw, c, p) for kw, c, p in keyword_data
             if c is not None and 11 <= c <= 20 and kw not in wins_kws]

    # --- Resumo ---
    improvements = sum(1 for _, c, p in keyword_data if c and p and c < p)
    declines = sum(1 for _, c, p in keyword_data if c and p and c > p)
    stable = sum(1 for _, c, p in keyword_data if c and p and c == p)
    new_entries = sum(1 for _, c, p in keyword_data if c and p is None)
    summary = f"{improvements} subindo • {declines} descendo • {stable} estável • {new_entries} novo(s)"

    # --- Seção: Atenção ---
    attention_html = ""
    if attention:
        rows = ""
        for kw, c, p in attention:
            diff = c - p
            rows += (
                f'<tr>'
                f'<td style="padding:8px 14px;color:#e0e0e0;font-size:14px">{kw}</td>'
                f'<td style="padding:8px 14px;text-align:right;color:#e53935;font-weight:bold">'
                f'#{c} <span style="font-size:12px;font-weight:normal">▼ {diff} pos</span></td>'
                f'</tr>'
            )
        attention_html = (
            '<tr><td style="padding:24px 32px 8px">'
            '<p style="margin:0 0 8px;color:#e53935;font-size:12px;font-weight:bold;'
            'text-transform:uppercase;letter-spacing:0.5px">🔴 Precisa da sua atenção</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:#2a1a1a;border-radius:8px;overflow:hidden">{rows}</table>'
            '<p style="margin:8px 0 0;color:#888;font-size:12px">Considere atualizar o '
            'conteúdo dessas páginas ou verificar a velocidade do site.</p>'
            '</td></tr>'
        )

    # --- Seção: Subindo ---
    wins_html = ""
    if wins:
        rows = ""
        for kw, c, p in wins:
            diff = p - c
            rows += (
                f'<tr>'
                f'<td style="padding:8px 14px;color:#e0e0e0;font-size:14px">{kw}</td>'
                f'<td style="padding:8px 14px;text-align:right;color:#4CAF50;font-weight:bold">'
                f'#{c} <span style="font-size:12px;font-weight:normal">▲ +{diff} pos</span></td>'
                f'</tr>'
            )
        wins_html = (
            '<tr><td style="padding:8px 32px">'
            '<p style="margin:0 0 8px;color:#4CAF50;font-size:12px;font-weight:bold;'
            'text-transform:uppercase;letter-spacing:0.5px">🟢 Subindo esta semana</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:#1a2a1a;border-radius:8px;overflow:hidden">{rows}</table>'
            '</td></tr>'
        )

    # --- Seção: Foco (posições 11–20) ---
    focus_html = ""
    if focus:
        rows = ""
        for kw, c, p in focus:
            if p is not None:
                diff = p - c
                trend_str = f" ▲ +{diff}" if diff > 0 else (f" ▼ {abs(diff)}" if diff < 0 else "")
            else:
                trend_str = " 🆕 Novo"
            rows += (
                f'<tr>'
                f'<td style="padding:8px 14px;color:#e0e0e0;font-size:14px">{kw}</td>'
                f'<td style="padding:8px 14px;text-align:right;color:#f5a623;font-weight:bold">'
                f'#{c} <span style="font-size:12px;color:#888;font-weight:normal">'
                f'— quase na pág. 1{trend_str}</span></td>'
                f'</tr>'
            )
        focus_html = (
            '<tr><td style="padding:8px 32px">'
            '<p style="margin:0 0 8px;color:#f5a623;font-size:12px;font-weight:bold;'
            'text-transform:uppercase;letter-spacing:0.5px">🎯 Foco desta semana — quase na página 1</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:#2a2210;border-radius:8px;overflow:hidden">{rows}</table>'
            '<p style="margin:8px 0 0;color:#888;font-size:12px">Essas palavras estão entre as '
            'posições 11–20. Um pouco mais de esforço pode colocá-las na primeira página do Google.</p>'
            '</td></tr>'
        )

    # --- Tabela completa ---
    rows_html = ""
    for kw, current, previous in keyword_data:
        trend = trend_html(current, previous)
        rows_html += (
            f'<tr>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #2a2a2a;color:#e0e0e0">{kw}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #2a2a2a;text-align:center">{trend}</td>'
            f'</tr>'
        )

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;overflow:hidden">

        <!-- Header -->
        <tr>
          <td style="background:#1a6de0;padding:28px 32px">
            <h1 style="margin:0;color:white;font-size:22px">📈 Seu Relatório Semanal de SEO</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px">{today} — SEO Brasil</p>
          </td>
        </tr>

        <!-- Resumo -->
        <tr>
          <td style="padding:24px 32px 8px">
            <p style="margin:0;color:#aaa;font-size:13px;text-align:center">{summary}</p>
          </td>
        </tr>

        {attention_html}
        {wins_html}
        {focus_html}

        <!-- Todas as palavras -->
        <tr>
          <td style="padding:24px 32px 8px">
            <p style="margin:0 0 8px;color:#888;font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px">Todas as palavras</p>
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <th style="padding:8px;text-align:left;color:#888;font-size:12px;text-transform:uppercase;border-bottom:1px solid #333">Palavra-chave</th>
                <th style="padding:8px;text-align:center;color:#888;font-size:12px;text-transform:uppercase;border-bottom:1px solid #333">Posição no Google</th>
              </tr>
              {rows_html}
            </table>
          </td>
        </tr>

        <!-- Feedback -->
        <tr>
          <td style="padding:24px 32px 8px;text-align:center;border-top:1px solid #2a2a2a">
            <p style="color:#888;font-size:13px;margin:0 0 14px">Este relatório foi útil hoje?</p>
            <a href="{feedback_up_url}" style="display:inline-block;background:#1a2a1a;color:#4CAF50;text-decoration:none;padding:8px 22px;border-radius:6px;font-size:14px;margin:0 6px;border:1px solid #2e5c2e">👍 Sim</a>
            <a href="{feedback_down_url}" style="display:inline-block;background:#2a1a1a;color:#e53935;text-decoration:none;padding:8px 22px;border-radius:6px;font-size:14px;margin:0 6px;border:1px solid #5c2e2e">👎 Não</a>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:16px 32px 32px;text-align:center">
            <a href="{APP_URL}" style="display:inline-block;background:#1a6de0;color:white;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:bold;font-size:15px">
              Ver meu monitoramento →
            </a>
            <p style="margin:16px 0 0;color:#555;font-size:12px">Dados atualizados toda segunda-feira • <a href="{APP_URL}" style="color:#555">seobrasil.app</a></p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return html


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


def upload_report_html(user_id, html):
    """Laddar upp HTML-rapporten till Supabase Storage och returnerar en signed URL (7 dagar)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = f"{user_id}/{date_str}.html"
    try:
        supabase.storage.from_("reports").upload(
            path=path,
            file=html.encode("utf-8"),
            file_options={"contentType": "text/html; charset=utf-8", "upsert": "true"},
        )
        res = supabase.storage.from_("reports").create_signed_url(
            path=path,
            expires_in=604800,  # 7 dagar
        )
        return res.get("signedURL") or res.get("signed_url") or ""
    except Exception as e:
        print(f"  Storage-fel: {e}")
        return ""


def log_report(user_id, keyword_count, status):
    supabase.table("weekly_reports").insert({
        "user_id": user_id,
        "keywords_tracked": keyword_count,
        "email_status": status,
    }).execute()


def run():
    print(f"=== Weekly Report kör {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    active_subscribers, expired_subscribers = get_active_subscribers()
    print(f"Aktiva: {len(active_subscribers)} | Expired trials: {len(expired_subscribers)}")

    # --- Teaser-mejl till expired trials ---
    for row in expired_subscribers:
        email = row.get("email")
        domain = row.get("domain")
        if not domain:
            print(f"  [teaser] {email} — ingen domän, hoppar över")
            continue
        html = build_teaser_html(email, domain)
        today = datetime.now().strftime("%d/%m/%Y")
        subject = f"⚠️ Sua análise semanal do Google está pronta (mas pausada)"
        ok = send_email(email, subject, html)
        print(f"  [teaser] {email} — {'skickat' if ok else 'fel'}")

    # --- Vanlig rapport till aktiva ---
    for row in active_subscribers:
        email = row.get("email")
        domain = row.get("domain")
        print(f"\n→ {email} | domän: {domain or '—'}")

        if not domain:
            print(f"  Ingen domän registrerad, hoppar över")
            continue

        user_id = get_user_id_by_email(email)
        if not user_id:
            print(f"  Kunde inte hitta user_id, hoppar över")
            continue

        keywords = get_tracked_keywords(user_id)
        if not keywords:
            print(f"  Inga spårade sökord, hoppar över")
            continue

        # Bygg rankingdata: (keyword, current_position, previous_position)
        keyword_data = []
        for kw in keywords:
            current, previous = get_keyword_ranking(user_id, domain, kw)
            keyword_data.append((kw, current, previous))

        # Skicka bara om det finns data
        if not any(c is not None for _, c, _ in keyword_data):
            print(f"  Ingen rankingdata ännu, hoppar över")
            continue

        html = build_email_html(email, keyword_data)
        today = datetime.now().strftime("%d/%m/%Y")
        subject = f"📈 Seu relatório SEO da semana — {today}"

        ok = send_email(email, subject, html)
        status = "sent" if ok else "failed"
        log_report(user_id, len(keywords), status)
        print(f"  E-post: {status}")

        # Ladda upp rapport till Supabase Storage → WhatsApp-länk
        report_url = upload_report_html(user_id, html)
        if report_url:
            print(f"  📲 WhatsApp-länk ({email}): {report_url}")
        else:
            print(f"  ⚠️  Kunde inte generera WhatsApp-länk")

    print("\n=== Weekly Report klar ===")


if __name__ == "__main__":
    run()

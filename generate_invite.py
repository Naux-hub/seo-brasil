"""
Generera en invite-token för SEO Brasil 14-dagars trial.

Kör:
    python generate_invite.py

Kräver att miljövariabeln SUPABASE_SERVICE_KEY är satt,
eller att du klistrar in nyckeln när skriptet frågar.
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from supabase import create_client

SUPABASE_URL = "https://knsxtaulmsiqeequrewx.supabase.co"


def main():
    key = os.environ.get("SUPABASE_SERVICE_KEY") or input("Service role key: ").strip()
    sb = create_client(SUPABASE_URL, key)

    email = input("E-mail do lead (opcional – Enter para pular): ").strip() or None
    days_str = input("Dias de validade do link (padrão 30): ").strip()
    days = int(days_str) if days_str.isdigit() else 30

    token = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    row = {"token": token, "expires_at": expires_at}
    if email:
        row["email"] = email

    sb.table("invite_tokens").insert(row).execute()

    url = f"https://seobrasil.app?invite_token={token}"
    print()
    print("✅ Token gerado com sucesso!")
    print(f"🔗 Link: {url}")
    print(f"📅 Expira em: {expires_at[:10]} ({days} dias)")
    if email:
        print(f"📧 Para: {email}")
    print()


if __name__ == "__main__":
    main()

dataforseo_pw = "d0f2f24acff7d679"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtuc3h0YXVsbXNpcWVlcXVyZXd4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI3ODE0MzQsImV4cCI6MjA5ODM1NzQzNH0.svs8xv4VbN49L5FkH-Lg6wAUuvc-C2ZVKY4NSCW_RpE"
stripe_key = "REMOVED"

content = f"""DATAFORSEO_LOGIN = "samuel.montelius@gmail.com"
DATAFORSEO_PASSWORD = "{dataforseo_pw}"
SUPABASE_URL = "https://knsxtaulmsiqeequrewx.supabase.co"
SUPABASE_KEY = "{supabase_key}"
STRIPE_SECRET_KEY = "{stripe_key}"
STRIPE_PRICE_ID = "price_1ToJf65UYkB5NuCvJAyu2ccF"
"""

with open(".streamlit/secrets.toml", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)

print("Klart!")
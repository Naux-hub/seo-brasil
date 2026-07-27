"""
rank_tracker.py — Hämtar Google-rankingar för alla aktiva prenumeranters spårade sökord.
Körs varje måndag via GitHub Actions.
Sparar resultat i Supabase-tabellen rank_history.
"""
 
import os
import requests
from datetime import datetime, timezone
from supabase import create_client
 
# --- Supabase-anslutning ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
 
# --- DataForSEO-inloggning ---
DATAFORSEO_LOGIN = os.environ["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = os.environ["DATAFORSEO_PASSWORD"]
 
LOCATION_CODE = 2076   # Brasilien
LANGUAGE_CODE = "pt"
DEPTH = 100            # Hämta top 100 resultat (billigare än fler)
 
 
def get_active_subscribers():
    """Hämtar alla aktiva prenumeranter."""
    res = supabase.table("subscribers").select("email").execute()
    return [r["email"] for r in res.data]
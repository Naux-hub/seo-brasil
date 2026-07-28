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


def get_user_id_by_email(email):
    """Hämtar user_id från subscribers-tabellen."""
    res = supabase.table("subscribers").select("user_id").eq("email", email).execute()
    if res.data and res.data[0].get("user_id"):
        return str(res.data[0]["user_id"])
    return None


def get_tracked_keywords(user_id):
    """Hämtar alla aktiva spårade sökord för en användare."""
    res = supabase.table("tracked_keywords") \
        .select("keyword") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    return [r["keyword"] for r in res.data]


def fetch_serp_positions(keywords):
    """
    Hämtar Google SERP-positioner för en lista sökord via DataForSEO Tasks API.
    Returnerar dict: {keyword: {position: int|None, url: str|None}}
    Kostnad: ~$0.0015 per sökord (mycket billigare än live-API).
    """
    results = {}

    # Steg 1: Posta tasks
    tasks = [
        {
            "keyword": kw,
            "location_code": LOCATION_CODE,
            "language_code": LANGUAGE_CODE,
            "depth": DEPTH,
        }
        for kw in keywords
    ]

    post_response = requests.post(
        "https://api.dataforseo.com/v3/serp/google/organic/task_post",
        auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
        json=tasks,
        timeout=30,
    )
    post_data = post_response.json()

    if post_data.get("status_code") != 20000:
        print(f"  DataForSEO task_post error: {post_data.get('status_message')}")
        return {kw: {"position": None, "url": None} for kw in keywords}

    # Samla task_ids och mappa keyword → task_id
    task_ids = {}
    for item in post_data.get("tasks", []):
        task_id = item.get("id")
        kw = item.get("data", {}).get("keyword")
        if task_id and kw:
            task_ids[task_id] = kw

    if not task_ids:
        return {kw: {"position": None, "url": None} for kw in keywords}

    # Steg 2: Hämta resultat (vänta lite för att tasks ska processas)
    import time
    time.sleep(15)

    for task_id, kw in task_ids.items():
        try:
            get_response = requests.get(
                f"https://api.dataforseo.com/v3/serp/google/organic/task_get/regular/{task_id}",
                auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
                timeout=30,
            )
            get_data = get_response.json()

            position = None
            url = None

            tasks_list = get_data.get("tasks", [])
            if tasks_list:
                result_items = tasks_list[0].get("result", [])
                if result_items:
                    items = result_items[0].get("items", [])
                    for item in items:
                        if item.get("type") == "organic":
                            position = item.get("rank_absolute")
                            url = item.get("url")
                            break

            results[kw] = {"position": position, "url": url}
            print(f"  {kw}: position {position}")

        except Exception as e:
            print(f"  Fel vid hämtning för '{kw}': {e}")
            results[kw] = {"position": None, "url": None}

    return results


def save_rank_history(user_id, keyword_results):
    """Sparar rankingresultat i rank_history-tabellen."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "keyword": kw,
            "position": data["position"],
            "url": data["url"],
            "checked_at": now,
        }
        for kw, data in keyword_results.items()
    ]
    if rows:
        supabase.table("rank_history").insert(rows).execute()


def run():
    """Huvudfunktion — körs varje måndag."""
    print(f"=== Rank Tracker kör {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    subscribers = get_active_subscribers()
    print(f"Hittade {len(subscribers)} aktiva prenumeranter")

    for email in subscribers:
        print(f"\n→ {email}")

        user_id = get_user_id_by_email(email)
        if not user_id:
            print(f"  Kunde inte hitta user_id för {email}, hoppar över")
            continue

        keywords = get_tracked_keywords(user_id)
        if not keywords:
            print(f"  Inga spårade sökord, hoppar över")
            continue

        print(f"  Spårar {len(keywords)} sökord: {keywords}")

        results = fetch_serp_positions(keywords)
        save_rank_history(user_id, results)
        print(f"  ✓ Sparat {len(results)} rankingar")

    print("\n=== Rank Tracker klar ===")


if __name__ == "__main__":
    run()

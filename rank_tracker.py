"""
rank_tracker.py — Hämtar Google-rankingar för alla aktiva prenumeranters spårade sökord.
Körs varje måndag via GitHub Actions.

Flöde per användare:
1. Hämta domän från subscribers (t.ex. seobrasil.app)
2. Hoppa över användare utan domän registrerad
3. Hämta sökord från tracked_keywords
4. Anropa DataForSEO SERP API — hitta var domänen rankar för varje sökord
5. Spara i keyword_rankings (upsert) med prev_rank_position för trendjämförelse
"""

import os
import time
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
DEPTH = 100            # Top 100 räcker och är billigare än fler


def get_active_subscribers():
    """Hämtar alla aktiva prenumeranter med e-post och domän."""
    res = supabase.table("subscribers").select("email, domain").execute()
    return res.data or []


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


def get_existing_positions(user_id, domain, keywords):
    """
    Hämtar nuvarande rank_position för varje sökord innan vi skriver över.
    Används för att fylla prev_rank_position vid nästa upsert.
    """
    if not keywords:
        return {}
    res = supabase.table("keyword_rankings") \
        .select("keyword, rank_position") \
        .eq("user_id", user_id) \
        .eq("domain", domain) \
        .in_("keyword", keywords) \
        .execute()
    return {r["keyword"]: r["rank_position"] for r in (res.data or [])}


def fetch_serp_positions(keywords, domain):
    """
    Hämtar Google SERP-positioner för en lista sökord via DataForSEO Tasks API.
    Söker specifikt efter användarens domän i resultaten (top 100).
    Returnerar dict: {keyword: {"position": int|None, "url": str|None}}

    Kostnad: ~$0.0012 per sökord (standard/async).
    """
    results = {kw: {"position": None, "url": None} for kw in keywords}

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

    try:
        post_response = requests.post(
            "https://api.dataforseo.com/v3/serp/google/organic/task_post",
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
            json=tasks,
            timeout=30,
        )
        post_data = post_response.json()
    except Exception as e:
        print(f"  Fel vid task_post: {e}")
        return results

    if post_data.get("status_code") != 20000:
        print(f"  DataForSEO task_post error: {post_data.get('status_message')}")
        return results

    # Samla task_ids → keyword-mappning
    task_ids = {}
    for item in post_data.get("tasks", []):
        task_id = item.get("id")
        kw = item.get("data", {}).get("keyword")
        if task_id and kw:
            task_ids[task_id] = kw

    if not task_ids:
        return results

    # Vänta på att tasks processas
    print(f"  Väntar 15s på DataForSEO...")
    time.sleep(15)

    # Steg 2: Hämta resultat och leta efter domänen
    for task_id, kw in task_ids.items():
        try:
            get_response = requests.get(
                f"https://api.dataforseo.com/v3/serp/google/organic/task_get/regular/{task_id}",
                auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
                timeout=30,
            )
            get_data = get_response.json()

            tasks_list = get_data.get("tasks", [])
            if not tasks_list:
                continue

            result_items = tasks_list[0].get("result", [])
            if not result_items:
                continue

            items = result_items[0].get("items", [])
            position = None
            url = None

            for item in items:
                if item.get("type") != "organic":
                    continue
                item_url = item.get("url", "") or ""
                item_domain = item.get("domain", "") or ""
                # Kolla om användarens domän finns i URL:en eller domänfältet
                if domain in item_url or domain in item_domain:
                    position = item.get("rank_absolute")
                    url = item_url
                    break

            results[kw] = {"position": position, "url": url}
            pos_str = f"#{position}" if position else "Ej i top 100"
            print(f"  {kw}: {pos_str}")

        except Exception as e:
            print(f"  Fel vid hämtning för '{kw}': {e}")

    return results


def save_keyword_rankings(user_id, domain, keyword_results, existing_positions):
    """
    Upserts rankingresultat i keyword_rankings-tabellen.
    Sparar nuvarande position som rank_position och
    föregående som prev_rank_position (för trendjämförelse i appen).
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "keyword": kw,
            "domain": domain,
            "rank_position": data["position"],
            "prev_rank_position": existing_positions.get(kw),
            "checked_at": now,
        }
        for kw, data in keyword_results.items()
    ]
    if rows:
        supabase.table("keyword_rankings").upsert(
            rows, on_conflict="user_id,keyword,domain"
        ).execute()


def run():
    """Huvudfunktion — körs varje måndag."""
    print(f"=== Rank Tracker kör {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    subscribers = get_active_subscribers()
    print(f"Hittade {len(subscribers)} aktiva prenumeranter")

    for row in subscribers:
        email = row.get("email")
        domain = row.get("domain")
        print(f"\n→ {email} | domän: {domain or '—'}")

        if not domain:
            print(f"  Ingen domän registrerad, hoppar över SERP-tracking")
            continue

        user_id = get_user_id_by_email(email)
        if not user_id:
            print(f"  Kunde inte hitta user_id, hoppar över")
            continue

        keywords = get_tracked_keywords(user_id)
        if not keywords:
            print(f"  Inga spårade sökord, hoppar över")
            continue

        print(f"  Spårar {len(keywords)} sökord för {domain}")

        existing = get_existing_positions(user_id, domain, keywords)
        results = fetch_serp_positions(keywords, domain)
        save_keyword_rankings(user_id, domain, results, existing)
        print(f"  ✓ Sparat {len(results)} rankingar")

    print("\n=== Rank Tracker klar ===")


if __name__ == "__main__":
    run()

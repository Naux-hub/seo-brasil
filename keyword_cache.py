"""
keyword_cache.py

Kostnadseffektivt caching- och batch-system för sökordsdata (DataForSEO + Supabase).
Marknad: Brasilien -> location_code=2076, language_code="pt" (hårdkodat).

Flöde i get_keyword_data():
    1. Slå upp alla sökord i Supabase keyword_cache-tabellen.
    2. Sökord < 30 dagar gamla -> cache-träff, inget API-anrop.
    3. Saknade/inaktuella sökord -> batchar om max 10 -> $0.09/batch.
    4. Batch-upsert: ett DB-anrop för alla nya resultat.
    5. Returnerar samlad data (cache + nyhämtat) för ALLA efterfrågade sökord.

Integrering i app.py:
    from keyword_cache import get_keyword_data
    results = get_keyword_data(sokordslista, supabase, login, password)
"""

import time
import logging
from datetime import datetime, timedelta, timezone

import requests

# ------------------------------------------------------------------
# Konfiguration
# ------------------------------------------------------------------

LOCATION_CODE = 2076        # Brasilien
LANGUAGE_CODE = "pt"        # Portugisiska
CACHE_MAX_AGE_DAYS = 30     # Data äldre än detta hämtas om
BATCH_SIZE = 10             # DataForSEO: max 10 sökord per task ($0.09/task)
SLEEP_BETWEEN_BATCHES = 0.5 # sekunder, undviker rate-limits vid stora listor

DATAFORSEO_ENDPOINT = (
    "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Hjälpfunktioner
# ------------------------------------------------------------------

def _is_fresh(cached_at_str: str) -> bool:
    """Kontrollerar om en cachad rad är yngre än CACHE_MAX_AGE_DAYS."""
    if not cached_at_str:
        return False
    try:
        cached_at = datetime.fromisoformat(cached_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - cached_at < timedelta(days=CACHE_MAX_AGE_DAYS)
    except (ValueError, AttributeError):
        return False


def _get_cached_keywords(supabase, keywords: list) -> dict:
    """
    Hämtar befintliga rader från keyword_cache för de efterfrågade sökorden.
    Returnerar dict: {keyword: row_dict} för alla träffar.
    """
    if not keywords:
        return {}
    try:
        response = (
            supabase.table("keyword_cache")
            .select("*")
            .eq("location_code", LOCATION_CODE)
            .eq("language_code", LANGUAGE_CODE)
            .in_("keyword", keywords)
            .execute()
        )
        return {row["keyword"]: row for row in (response.data or [])}
    except Exception as e:
        logger.error(f"Fel vid Supabase-lookup: {e}")
        return {}


def _fetch_from_dataforseo(batch: list, login: str, password: str) -> list:
    """
    Gör ETT API-anrop för en batch om max 10 sökord.
    Returnerar lista av dicts med rådata från DataForSEO.
    Returnerar [] vid fel (kraschar aldrig pipelinen).
    """
    payload = [
        {
            "keywords": batch,
            "location_code": LOCATION_CODE,
            "language_code": LANGUAGE_CODE,
        }
    ]
    try:
        response = requests.post(
            DATAFORSEO_ENDPOINT,
            json=payload,
            auth=(login, password),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as e:
        logger.error(f"DataForSEO API-anrop misslyckades för batch {batch}: {e}")
        return []

    tasks = body.get("tasks") or []
    if not tasks:
        logger.warning(f"Tomt 'tasks'-svar från DataForSEO för batch: {batch}")
        return []

    results = []
    for task in tasks:
        for item in (task.get("result") or []):
            if item:
                results.append(item)
    return results


def _batch_upsert(supabase, items: list) -> None:
    """
    Sparar alla nya resultat till keyword_cache i ETT DB-anrop (batch upsert).
    Tidigare: ett anrop per sökord. Nu: ett anrop per batch -> färre DB-runder.
    """
    if not items:
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "keyword": item.get("keyword", ""),
            "location_code": LOCATION_CODE,
            "language_code": LANGUAGE_CODE,
            "search_volume": item.get("search_volume") or 0,
            "competition": str(item.get("competition", "N/A")),
            "cpc": float(item["cpc"]) if item.get("cpc") else None,
            "cached_at": now,
        }
        for item in items
        if item.get("keyword")
    ]
    if rows:
        try:
            supabase.table("keyword_cache").upsert(
                rows, on_conflict="keyword,location_code,language_code"
            ).execute()
            logger.info(f"Upsertade {len(rows)} rader i keyword_cache.")
        except Exception as e:
            logger.error(f"Fel vid upsert till Supabase: {e}")


# ------------------------------------------------------------------
# Huvudfunktion
# ------------------------------------------------------------------

def get_keyword_data(keywords: list, supabase, login: str, password: str) -> list:
    """
    Returnerar sökordsdata för alla efterfrågade sökord.
    Cache-first: anropar DataForSEO enbart för ord som saknas eller > 30 dagar gamla.

    Args:
        keywords:  Lista med sökord, t.ex. ["seo brasil", "marketing digital"]
        supabase:  Supabase-client (skickad från app.py, använder st.secrets)
        login:     DataForSEO login
        password:  DataForSEO password

    Returns:
        list of dicts med nycklarna: keyword, search_volume, competition, cpc

    Kostnad: $0.09 per batch om 10 sökord (enbart cache-missar).
    Exempel: 10 ord redan cachade = $0.00. 10 nya ord = $0.09.
    """
    # Rensa dubbletter och tomma strängar
    seen = set()
    clean = []
    for kw in keywords:
        kw = (kw or "").strip()
        if kw and kw not in seen:
            seen.add(kw)
            clean.append(kw)

    if not clean:
        return []

    # 1. Kolla cache
    cached_rows = _get_cached_keywords(supabase, clean)

    final_results = []
    to_fetch = []

    for kw in clean:
        row = cached_rows.get(kw)
        if row and _is_fresh(row.get("cached_at", "")):
            final_results.append({
                "keyword": row["keyword"],
                "search_volume": row["search_volume"],
                "competition": row["competition"],
                "cpc": row["cpc"],
            })
        else:
            to_fetch.append(kw)

    logger.info(
        f"{len(final_results)} sökord från cache, "
        f"{len(to_fetch)} hämtas från DataForSEO."
    )

    # 2. Hämta cache-missar i batchar om 10
    if to_fetch:
        batches = [to_fetch[i:i + BATCH_SIZE] for i in range(0, len(to_fetch), BATCH_SIZE)]
        all_api_items = []

        for i, batch in enumerate(batches, start=1):
            logger.info(f"Batch {i}/{len(batches)}: {len(batch)} sökord...")
            items = _fetch_from_dataforseo(batch, login, password)
            all_api_items.extend(items)
            if items:
                for item in items:
                    final_results.append({
                        "keyword": item.get("keyword", ""),
                        "search_volume": item.get("search_volume") or 0,
                        "competition": str(item.get("competition", "N/A")),
                        "cpc": item.get("cpc") or 0,
                    })
            if i < len(batches):
                time.sleep(SLEEP_BETWEEN_BATCHES)

        # 3. Batch-upsert alla nya resultat i ett DB-anrop
        _batch_upsert(supabase, all_api_items)

    return final_results

"""
keyword_cache.py

Kostnadseffektivt caching- och batch-system för sökordsdata (DataForSEO + Supabase).

Marknad väljs via miljövariabel MARKET (standard: "br"):
  MARKET=br → Brasilien, location_code=2076, language_code="pt"
  MARKET=mx → México, location_code=2484, language_code="es"

Om MARKET saknas eller är "br" är beteendet identiskt med tidigare version.

Flöde i get_keyword_data():
    1. Slå upp alla sökord i Supabase keyword_cache-tabellen.
    2. Sökord < 30 dagar gamla med KD -> cache-träff, inget API-anrop.
    3. Sökord < 30 dagar gamla men KD=NULL -> hämtar KD, uppdaterar cache.
    4. Saknade/inaktuella sökord -> batchar om max 10 -> $0.09/batch.
    5. KD hämtas i ett bulk-anrop för alla cache-missar + KD-saknade.
    6. Batch-upsert: ett DB-anrop för alla nya resultat.
    7. Returnerar samlad data (cache + nyhämtat) för ALLA efterfrågade sökord.

Integrering i app.py:
    from keyword_cache import get_keyword_data
    results = get_keyword_data(sokordslista, supabase, login, password)
"""

import time
import logging
from datetime import datetime, timedelta, timezone

import requests
from market_config import get_market, market_from_env

# ------------------------------------------------------------------
# Konfiguration
# ------------------------------------------------------------------

# Marknadsval: läs MARKET från miljövariabel, standard "br"
_MARKET = market_from_env()
_market_cfg = get_market(_MARKET)
LOCATION_CODE = _market_cfg["location_code"]   # 2076 (BR) eller 2484 (MX)
LANGUAGE_CODE = _market_cfg["language_code"]   # "pt" (BR) eller "es" (MX)
CACHE_MAX_AGE_DAYS = 30     # Data äldre än detta hämtas om
BATCH_SIZE = 10             # DataForSEO: max 10 sökord per task ($0.09/task)
SLEEP_BETWEEN_BATCHES = 0.5 # sekunder, undviker rate-limits vid stora listor

DATAFORSEO_ENDPOINT = (
    "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
)

KD_ENDPOINT = (
    "https://api.dataforseo.com/v3/dataforseo_labs/google/bulk_keyword_difficulty/live"
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


def _fetch_keyword_difficulty(keywords: list, login: str, password: str) -> dict:
    """
    Hämtar Keyword Difficulty (0-100) för upp till 1000 sökord i ett anrop.
    Returnerar {keyword: int_kd} för alla hittade sökord.
    Returnerar {} vid fel (graceful failure — påverkar aldrig pipelinen).

    Endpoint: POST /v3/dataforseo_labs/google/bulk_keyword_difficulty/live
    Kostnad: $0.012/task + $0.00012/keyword (under "All Other Endpoints"-prissättning)
    """
    if not keywords:
        return {}
    payload = [{
        "keywords": list(keywords),
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
    }]
    try:
        response = requests.post(
            KD_ENDPOINT,
            json=payload,
            auth=(login, password),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as e:
        logger.error(f"DataForSEO bulk_keyword_difficulty misslyckades: {e}")
        return {}

    tasks = body.get("tasks") or []
    if not tasks:
        logger.warning("Tomt 'tasks'-svar från bulk_keyword_difficulty")
        return {}

    kd_map = {}
    for task in tasks:
        for result in (task.get("result") or []):
            for item in (result.get("items") or []):
                kw = item.get("keyword")
                kd = item.get("keyword_difficulty")
                if kw and kd is not None:
                    kd_map[kw] = int(kd)

    logger.info(f"KD hämtad för {len(kd_map)}/{len(keywords)} sökord")
    return kd_map


def _batch_upsert(supabase, items: list) -> None:
    """
    Sparar alla nya resultat till keyword_cache i ETT DB-anrop (batch upsert).
    Items kan innehålla keyword_difficulty (int eller None).
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
            "keyword_difficulty": item.get("keyword_difficulty"),
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


def _update_kd_in_cache(supabase, kd_map: dict) -> None:
    """
    Uppdaterar keyword_difficulty för befintliga, färska cache-rader
    som saknade KD (NULL). Berör inga andra kolumner.
    """
    if not kd_map:
        return
    rows = [
        {
            "keyword": kw,
            "location_code": LOCATION_CODE,
            "language_code": LANGUAGE_CODE,
            "keyword_difficulty": kd,
        }
        for kw, kd in kd_map.items()
    ]
    if rows:
        try:
            supabase.table("keyword_cache").upsert(
                rows, on_conflict="keyword,location_code,language_code"
            ).execute()
            logger.info(f"Uppdaterade KD för {len(rows)} cachade sökord.")
        except Exception as e:
            logger.error(f"Fel vid uppdatering av keyword_difficulty: {e}")


# ------------------------------------------------------------------
# Keyword ideas (relaterade sökord via keywords_for_keywords)
# ------------------------------------------------------------------

KEYWORD_IDEAS_ENDPOINT = (
    "https://api.dataforseo.com/v3/keywords_data/google_ads/keywords_for_keywords/live"
)


def _get_cached_ideas(supabase, seeds_key: str) -> list | None:
    """Returnerar cachade idéer om de finns och är färska, annars None."""
    try:
        res = (
            supabase.table("keyword_ideas_cache")
            .select("results, cached_at")
            .eq("seeds_key", seeds_key)
            .execute()
        )
        if res.data:
            row = res.data[0]
            if _is_fresh(row["cached_at"]):
                logger.info(f"Idéer för '{seeds_key}' hämtades från cache.")
                return row["results"]
    except Exception as e:
        logger.error(f"Fel vid lookup av keyword_ideas_cache: {e}")
    return None


def _set_cached_ideas(supabase, seeds_key: str, results: list) -> None:
    """Sparar idéer i keyword_ideas_cache."""
    try:
        supabase.table("keyword_ideas_cache").upsert(
            {
                "seeds_key": seeds_key,
                "results": results,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="seeds_key",
        ).execute()
        logger.info(f"Sparade {len(results)} idéer i cache för '{seeds_key}'.")
    except Exception as e:
        logger.error(f"Fel vid upsert av keyword_ideas_cache: {e}")


def get_keyword_ideas(
    seed_keywords: list,
    supabase,
    login: str,
    password: str,
    limit: int = 10,
) -> list:
    """
    Hämtar relaterade sökord baserat på seed-sökorden.
    Cache-first: returnerar cachade idéer om de finns (< 30 dagar gamla).
    Vid cache-miss: anropar DataForSEO och sparar resultatet.

    Args:
        seed_keywords:  Lista med seed-sökord (max 10, vi skickar max 5)
        supabase:       Supabase-client
        login/password: DataForSEO-uppgifter
        limit:          Max antal förslag att returnera

    Returns:
        list of dicts med nycklarna: keyword, search_volume, competition, cpc,
        keyword_difficulty (int 0-100 eller None)
        Sorterat på search_volume fallande.
    """
    seeds = [kw for kw in seed_keywords if kw][:5]
    if not seeds:
        return []

    seeds_key = "|".join(sorted(s.lower() for s in seeds))

    # 1. Kolla cache
    cached = _get_cached_ideas(supabase, seeds_key)
    if cached is not None:
        return cached[:limit]

    # 2. Cache-miss — hämta från DataForSEO
    payload = [{
        "keywords": seeds,
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
    }]

    try:
        response = requests.post(
            KEYWORD_IDEAS_ENDPOINT,
            json=payload,
            auth=(login, password),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as e:
        logger.error(f"DataForSEO keywords_for_keywords misslyckades: {e}")
        return []

    tasks = body.get("tasks") or []
    if not tasks:
        return []

    api_items = []
    results = []
    for task in tasks:
        for item in (task.get("result") or []):
            if item and item.get("keyword"):
                api_items.append(item)
                results.append({
                    "keyword": item.get("keyword", ""),
                    "search_volume": item.get("search_volume") or 0,
                    "competition": str(item.get("competition", "N/A")),
                    "cpc": item.get("cpc") or 0,
                    "keyword_difficulty": None,
                })

    # Filtrera bort förslag med duplicerade ord ("whey whey protein", "protein whey protein")
    def _has_duplicate_words(kw: str) -> bool:
        words = kw.lower().split()
        return len(words) != len(set(words))

    results = [r for r in results if not _has_duplicate_words(r["keyword"])]

    # Sortera på sökvolym och returnera top N
    results.sort(key=lambda x: x.get("search_volume", 0), reverse=True)
    final = results[:limit]

    # Hämta KD — cache-first: kolla keyword_cache innan API-anrop
    idea_keywords = [r["keyword"] for r in final]
    cached_kd_rows = _get_cached_keywords(supabase, idea_keywords)
    kd_to_fetch = []

    for r in final:
        cr = cached_kd_rows.get(r["keyword"])
        if cr and _is_fresh(cr.get("cached_at", "")) and cr.get("keyword_difficulty") is not None:
            r["keyword_difficulty"] = cr["keyword_difficulty"]   # cache-träff
        else:
            r["keyword_difficulty"] = None
            kd_to_fetch.append(r["keyword"])                     # behöver hämtas

    kd_map = {}
    if kd_to_fetch:
        kd_map = _fetch_keyword_difficulty(kd_to_fetch, login, password)
        for r in final:
            if r["keyword"] in kd_map:
                r["keyword_difficulty"] = kd_map[r["keyword"]]

        # Uppdatera KD för färska keyword_cache-rader som hade KD=NULL
        kd_for_fresh_update = {}
        for kw in kd_to_fetch:
            if kw in kd_map:
                cr = cached_kd_rows.get(kw)
                if cr and _is_fresh(cr.get("cached_at", "")):
                    kd_for_fresh_update[kw] = kd_map[kw]
        if kd_for_fresh_update:
            _update_kd_in_cache(supabase, kd_for_fresh_update)

    # Sätt KD på api_items inför upsert — använd fetched eller cached KD
    for item in api_items:
        kw = item.get("keyword", "")
        if kw in kd_map:
            item["keyword_difficulty"] = kd_map[kw]
        else:
            cr = cached_kd_rows.get(kw)
            item["keyword_difficulty"] = cr.get("keyword_difficulty") if cr else None

    # Spara individuella sökord i keyword_cache (inkl. KD)
    _batch_upsert(supabase, api_items)

    # 3. Spara i keyword_ideas_cache — gratis nästa gång
    _set_cached_ideas(supabase, seeds_key, final)

    return final


# ------------------------------------------------------------------
# Huvudfunktion
# ------------------------------------------------------------------

def get_keyword_data(keywords: list, supabase, login: str, password: str) -> list:
    """
    Returnerar sökordsdata för alla efterfrågade sökord.
    Cache-first: anropar DataForSEO enbart för ord som saknas eller > 30 dagar gamla.
    KD hämtas separat via bulk_keyword_difficulty för cache-missar och rader med KD=NULL.

    Args:
        keywords:  Lista med sökord, t.ex. ["seo brasil", "marketing digital"]
        supabase:  Supabase-client (skickad från app.py, använder st.secrets)
        login:     DataForSEO login
        password:  DataForSEO password

    Returns:
        list of dicts med nycklarna: keyword, search_volume, competition, cpc,
        keyword_difficulty (int 0-100 eller None vid misslyckad KD-hämtning)

    Kostnad: $0.09 per batch om 10 sökord (enbart cache-missar).
             $0.012 + $0.00012/kw för KD-batch (alla missar + KD-saknade i ett anrop).
    Exempel: 10 ord cachade med KD = $0.00. 10 nya ord = $0.09 + ~$0.013.
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
    to_fetch = []        # Saknas i cache eller är inaktuella — behöver full datahämtning
    kd_update_needed = []  # Färska rader men keyword_difficulty = NULL

    for kw in clean:
        row = cached_rows.get(kw)
        if row and _is_fresh(row.get("cached_at", "")):
            kd = row.get("keyword_difficulty")
            final_results.append({
                "keyword": row["keyword"],
                "search_volume": row["search_volume"],
                "competition": row["competition"],
                "cpc": row["cpc"],
                "keyword_difficulty": kd,
            })
            if kd is None:
                kd_update_needed.append(kw)
        else:
            to_fetch.append(kw)

    logger.info(
        f"{len(final_results)} sökord från cache "
        f"({len(kd_update_needed)} saknar KD), "
        f"{len(to_fetch)} hämtas från DataForSEO."
    )

    # 2. Hämta cache-missar i batchar om 10
    all_api_items = []
    if to_fetch:
        batches = [to_fetch[i:i + BATCH_SIZE] for i in range(0, len(to_fetch), BATCH_SIZE)]

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
                        "keyword_difficulty": None,  # fylls i nedan
                    })
            if i < len(batches):
                time.sleep(SLEEP_BETWEEN_BATCHES)

    # 3. Hämta KD i ett enda bulk-anrop för alla som behöver det
    #    (cache-missar + färska rader med KD=NULL)
    kd_needed = to_fetch + kd_update_needed
    if kd_needed:
        kd_map = _fetch_keyword_difficulty(kd_needed, login, password)

        # Applicera KD på final_results
        for r in final_results:
            if r["keyword_difficulty"] is None and r["keyword"] in kd_map:
                r["keyword_difficulty"] = kd_map[r["keyword"]]

        # Lägg KD på api_items (cache-missar) inför upsert
        for item in all_api_items:
            item["keyword_difficulty"] = kd_map.get(item.get("keyword", ""))

        # Uppdatera bara KD för färska rader som saknade det
        if kd_update_needed:
            kd_for_fresh = {kw: kd_map[kw] for kw in kd_update_needed if kw in kd_map}
            if kd_for_fresh:
                _update_kd_in_cache(supabase, kd_for_fresh)

    # 4. Batch-upsert nya resultat (cache-missar) med KD
    if all_api_items:
        _batch_upsert(supabase, all_api_items)

    return final_results

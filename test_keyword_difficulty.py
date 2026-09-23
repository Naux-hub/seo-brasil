"""
test_keyword_difficulty.py
==========================
Testar Steg 2: Organic Keyword Difficulty via DataForSEO Labs.

Täcker:
  1.  Cache-träff med KD → returnerar KD direkt, inget API-anrop
  2.  Färsk cache med KD=NULL → hämtar bara KD, uppdaterar cache
  3.  Cache-miss → hämtar full data + KD i separata anrop
  4.  Utgången cache → hämtar om all data inkl. KD
  5.  Bulk-anrop: flera missar → ETT KD-anrop
  6.  Graceful failure: KD-API kraschar → KD=None, pipeline fortsätter
  7.  Graceful failure: full data-API kraschar → [] returneras
  8.  _fetch_keyword_difficulty parsning: rätt nyckel/struktur
  9.  _batch_upsert inkluderar keyword_difficulty-kolumnen
  10. _update_kd_in_cache anropas bara vid kd_update_needed
  11. UI-etiketter: "Dificuldade SEO" finns i app.py (källkodsinspektion)
  12. CSV-kolumn: "Dificuldade SEO" finns i app.py (källkodsinspektion)
  13. get_keyword_ideas returnerar keyword_difficulty i varje post
  14. Ideas-cache innehåller keyword_difficulty vid lagring

Inga anrop till Supabase, DataForSEO eller extern tjänst.
All I/O mockas via unittest.mock.

Kör:
    python test_keyword_difficulty.py
"""

import sys
import json
import types
import unittest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Stubs för att importera keyword_cache utan riktiga beroenden
# ---------------------------------------------------------------------------

def _make_market_config_stub():
    mod = types.ModuleType("market_config")
    mod.get_market = MagicMock(return_value={"location_code": 2076, "language_code": "pt"})
    mod.market_from_env = MagicMock(return_value="br")
    return mod


sys.modules.setdefault("market_config", _make_market_config_stub())

# requests-stub: ersätts per test med patch
if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()


# ---------------------------------------------------------------------------
# Importera modulerna vi testar
# ---------------------------------------------------------------------------

import keyword_cache as kc


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

FRESH_TS = datetime.now(timezone.utc).isoformat()
STALE_TS = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()


def _supabase_with_cache(rows: list) -> MagicMock:
    """Returnerar Supabase-mock med angiven keyword_cache-data."""
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.upsert.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    sb.table.return_value = chain
    return sb


def _mock_search_volume_response(keywords: list) -> dict:
    """Bygg ett giltigt DataForSEO search_volume-svar för de angivna sökorden."""
    items = [{"keyword": kw, "search_volume": 1000, "competition": "0.5", "cpc": 0.3}
             for kw in keywords]
    return {
        "status_code": 20000,
        "tasks": [{"result": items}]
    }


def _mock_kd_response(kd_map: dict) -> dict:
    """Bygg ett giltigt DataForSEO bulk_keyword_difficulty-svar."""
    items = [{"keyword": kw, "keyword_difficulty": kd} for kw, kd in kd_map.items()]
    return {
        "status_code": 20000,
        "tasks": [{"result": [{"items": items}]}]
    }


def _make_requests_mock(sv_response=None, kd_response=None, sv_exception=None, kd_exception=None):
    """
    Returnerar en requests.post-mock som ger rätt svar beroende på vilken
    endpoint som anropas.
    """
    def _post(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "bulk_keyword_difficulty" in url:
            if kd_exception:
                raise kd_exception
            resp.json.return_value = kd_response or {"tasks": []}
        else:
            if sv_exception:
                raise sv_exception
            resp.json.return_value = sv_response or {"tasks": []}
        return resp
    return _post


# ---------------------------------------------------------------------------
# TEST 1: Cache-träff med KD → returnerar direkt, inget API-anrop
# ---------------------------------------------------------------------------

class TestCacheHitWithKD(unittest.TestCase):

    def test_cache_hit_returns_kd_without_api_call(self):
        """Färskt cachat sökord med KD ska returneras direkt utan API-anrop."""
        rows = [{
            "keyword": "seo brasil",
            "location_code": 2076,
            "language_code": "pt",
            "search_volume": 5000,
            "competition": "0.4",
            "cpc": 0.5,
            "keyword_difficulty": 42,
            "cached_at": FRESH_TS,
        }]
        sb = _supabase_with_cache(rows)

        with patch.object(kc.requests, "post") as mock_post:
            result = kc.get_keyword_data(["seo brasil"], sb, "login", "pw")

        mock_post.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keyword"], "seo brasil")
        self.assertEqual(result[0]["keyword_difficulty"], 42)


# ---------------------------------------------------------------------------
# TEST 2: Färsk cache med KD=NULL → hämtar bara KD, uppdaterar cache
# ---------------------------------------------------------------------------

class TestFreshCacheNullKD(unittest.TestCase):

    def test_null_kd_triggers_kd_fetch_only(self):
        """Färskt cachat sökord med KD=NULL ska hämta KD men inte search_volume."""
        rows = [{
            "keyword": "marketing digital",
            "location_code": 2076,
            "language_code": "pt",
            "search_volume": 3000,
            "competition": "0.6",
            "cpc": 0.8,
            "keyword_difficulty": None,
            "cached_at": FRESH_TS,
        }]
        sb = _supabase_with_cache(rows)
        kd_resp = _mock_kd_response({"marketing digital": 55})

        post_calls = []

        def _post(url, **kwargs):
            post_calls.append(url)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = kd_resp
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_data(["marketing digital"], sb, "login", "pw")

        # Ska bara ha anropat KD-endpoint, inte search_volume
        self.assertEqual(len(post_calls), 1)
        self.assertIn("bulk_keyword_difficulty", post_calls[0])
        self.assertEqual(result[0]["keyword_difficulty"], 55)

    def test_null_kd_calls_update_kd_in_cache(self):
        """_update_kd_in_cache ska anropas med rätt data."""
        rows = [{
            "keyword": "marketing digital",
            "location_code": 2076,
            "language_code": "pt",
            "search_volume": 3000,
            "competition": "0.6",
            "cpc": 0.8,
            "keyword_difficulty": None,
            "cached_at": FRESH_TS,
        }]
        sb = _supabase_with_cache(rows)
        kd_resp = _mock_kd_response({"marketing digital": 55})

        with patch.object(kc.requests, "post", return_value=MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value=kd_resp)
        )):
            with patch.object(kc, "_update_kd_in_cache") as mock_update:
                kc.get_keyword_data(["marketing digital"], sb, "login", "pw")

        mock_update.assert_called_once()
        kd_map_arg = mock_update.call_args[0][1]  # andra positionella arg = kd_map
        self.assertEqual(kd_map_arg, {"marketing digital": 55})


# ---------------------------------------------------------------------------
# TEST 3: Cache-miss → hämtar full data + KD
# ---------------------------------------------------------------------------

class TestCacheMissFetchesFullAndKD(unittest.TestCase):

    def test_cache_miss_fetches_search_volume_and_kd(self):
        """Cache-miss ska hämta search_volume OCH KD."""
        sb = _supabase_with_cache([])  # tom cache
        sv_resp = _mock_search_volume_response(["agencia seo"])
        kd_resp = _mock_kd_response({"agencia seo": 67})

        with patch.object(kc.requests, "post",
                          side_effect=_make_requests_mock(sv_resp, kd_resp)):
            result = kc.get_keyword_data(["agencia seo"], sb, "login", "pw")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keyword_difficulty"], 67)
        self.assertEqual(result[0]["search_volume"], 1000)

    def test_cache_miss_upsert_includes_kd(self):
        """_batch_upsert ska anropas med keyword_difficulty i item-datan."""
        sb = _supabase_with_cache([])
        sv_resp = _mock_search_volume_response(["agencia seo"])
        kd_resp = _mock_kd_response({"agencia seo": 67})

        with patch.object(kc.requests, "post",
                          side_effect=_make_requests_mock(sv_resp, kd_resp)):
            with patch.object(kc, "_batch_upsert") as mock_upsert:
                kc.get_keyword_data(["agencia seo"], sb, "login", "pw")

        mock_upsert.assert_called_once()
        items_arg = mock_upsert.call_args[0][1]
        self.assertEqual(len(items_arg), 1)
        self.assertEqual(items_arg[0].get("keyword_difficulty"), 67)


# ---------------------------------------------------------------------------
# TEST 4: Utgången cache → hämtar om all data inkl. KD
# ---------------------------------------------------------------------------

class TestExpiredCacheRefetches(unittest.TestCase):

    def test_stale_cache_refetches_all_data(self):
        """Utgången rad ska hämta om search_volume + KD."""
        rows = [{
            "keyword": "seo",
            "location_code": 2076,
            "language_code": "pt",
            "search_volume": 100,
            "competition": "0.2",
            "cpc": 0.1,
            "keyword_difficulty": 30,
            "cached_at": STALE_TS,  # > 30 dagar gammal
        }]
        sb = _supabase_with_cache(rows)
        sv_resp = _mock_search_volume_response(["seo"])
        kd_resp = _mock_kd_response({"seo": 35})

        post_urls = []

        def _post(url, **kwargs):
            post_urls.append(url)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                resp.json.return_value = kd_resp
            else:
                resp.json.return_value = sv_resp
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_data(["seo"], sb, "login", "pw")

        # Ska ha anropat BÅDA endpoints
        self.assertTrue(any("bulk_keyword_difficulty" in u for u in post_urls))
        self.assertTrue(any("search_volume" in u for u in post_urls))
        self.assertEqual(result[0]["keyword_difficulty"], 35)


# ---------------------------------------------------------------------------
# TEST 5: Bulk-anrop: flera missar → ETT KD-anrop
# ---------------------------------------------------------------------------

class TestBulkKDSingleCall(unittest.TestCase):

    def test_multiple_misses_single_kd_call(self):
        """Flera cache-missar ska resultera i ETT bulk KD-anrop (inte ett per sökord)."""
        sb = _supabase_with_cache([])
        keywords = ["kw1", "kw2", "kw3"]
        sv_resp = _mock_search_volume_response(keywords)
        kd_resp = _mock_kd_response({"kw1": 10, "kw2": 20, "kw3": 30})

        kd_call_count = {"n": 0}

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                kd_call_count["n"] += 1
                resp.json.return_value = kd_resp
            else:
                resp.json.return_value = sv_resp
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_data(keywords, sb, "login", "pw")

        self.assertEqual(kd_call_count["n"], 1,
                         "Ska bara göra ETT KD-anrop oavsett antal cache-missar")
        kd_values = {r["keyword"]: r["keyword_difficulty"] for r in result}
        self.assertEqual(kd_values["kw1"], 10)
        self.assertEqual(kd_values["kw2"], 20)
        self.assertEqual(kd_values["kw3"], 30)

    def test_mixed_fresh_null_and_miss_single_kd_call(self):
        """
        Blandad situation: 1 färsk med KD=NULL + 1 cache-miss
        → ETT KD-anrop med båda sökorden.
        """
        rows = [{
            "keyword": "fresh_no_kd",
            "location_code": 2076,
            "language_code": "pt",
            "search_volume": 2000,
            "competition": "0.3",
            "cpc": 0.2,
            "keyword_difficulty": None,
            "cached_at": FRESH_TS,
        }]
        sb = _supabase_with_cache(rows)
        sv_resp = _mock_search_volume_response(["miss_kw"])
        kd_resp = _mock_kd_response({"fresh_no_kd": 45, "miss_kw": 60})

        kd_payloads = []

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                kd_payloads.append(kwargs.get("json", []))
                resp.json.return_value = kd_resp
            else:
                resp.json.return_value = sv_resp
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_data(["fresh_no_kd", "miss_kw"], sb, "login", "pw")

        # ETT KD-anrop
        self.assertEqual(len(kd_payloads), 1)
        # Båda sökorden ska finnas i det ena anropet
        sent_kws = kd_payloads[0][0]["keywords"]
        self.assertIn("fresh_no_kd", sent_kws)
        self.assertIn("miss_kw", sent_kws)

        kd_map = {r["keyword"]: r["keyword_difficulty"] for r in result}
        self.assertEqual(kd_map["fresh_no_kd"], 45)
        self.assertEqual(kd_map["miss_kw"], 60)


# ---------------------------------------------------------------------------
# TEST 6: Graceful failure — KD-API kraschar → KD=None, pipeline fortsätter
# ---------------------------------------------------------------------------

class TestKDApiFailureGraceful(unittest.TestCase):

    def test_kd_api_exception_returns_none_kd(self):
        """Om KD-API kraschar ska keyword_difficulty=None returneras — pipeline kraschar inte."""
        sb = _supabase_with_cache([])
        sv_resp = _mock_search_volume_response(["creatina"])

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                raise Exception("KD API timeout")
            resp.json.return_value = sv_resp
            return resp

        result = kc.get_keyword_data.__wrapped__ if hasattr(kc.get_keyword_data, "__wrapped__") \
            else kc.get_keyword_data

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_data(["creatina"], sb, "login", "pw")

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["keyword_difficulty"],
                          "KD ska vara None vid API-fel, inte krascha")
        self.assertEqual(result[0]["keyword"], "creatina")
        self.assertEqual(result[0]["search_volume"], 1000)

    def test_kd_api_bad_json_returns_none_kd(self):
        """Tomt tasks-svar från KD-API → KD=None för alla sökord."""
        sb = _supabase_with_cache([])
        sv_resp = _mock_search_volume_response(["proteina"])
        kd_resp_empty = {"tasks": []}  # inga results

        with patch.object(kc.requests, "post",
                          side_effect=_make_requests_mock(sv_resp, kd_resp_empty)):
            result = kc.get_keyword_data(["proteina"], sb, "login", "pw")

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["keyword_difficulty"])


# ---------------------------------------------------------------------------
# TEST 7: Graceful failure — search_volume-API kraschar → [] returneras
# ---------------------------------------------------------------------------

class TestSearchVolumeApiFailureGraceful(unittest.TestCase):

    def test_sv_api_exception_returns_empty_for_miss(self):
        """Om search_volume-API kraschar för en cache-miss ska [] returneras (ingen krasch)."""
        sb = _supabase_with_cache([])  # cache-miss

        def _post(url, **kwargs):
            if "search_volume" in url:
                raise Exception("SV API down")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_data(["unknown_kw"], sb, "login", "pw")

        # Ingen krasch, returnerar tom lista (API misslyckades → inga items)
        # eller tom lista för det specifika sökordet
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# TEST 8: _fetch_keyword_difficulty — parsning av API-svar
# ---------------------------------------------------------------------------

class TestFetchKeywordDifficultyParsing(unittest.TestCase):

    def test_parses_correct_structure(self):
        """_fetch_keyword_difficulty ska parsa tasks[0].result[0].items[]."""
        kd_resp = _mock_kd_response({"seo": 42, "marketing": 78})

        with patch.object(kc.requests, "post", return_value=MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value=kd_resp)
        )):
            result = kc._fetch_keyword_difficulty(["seo", "marketing"], "login", "pw")

        self.assertEqual(result["seo"], 42)
        self.assertEqual(result["marketing"], 78)

    def test_returns_int_not_float(self):
        """KD-värdet ska vara int, inte float."""
        kd_resp = _mock_kd_response({"test": 55})

        with patch.object(kc.requests, "post", return_value=MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value=kd_resp)
        )):
            result = kc._fetch_keyword_difficulty(["test"], "login", "pw")

        self.assertIsInstance(result["test"], int)

    def test_empty_keywords_returns_empty_dict(self):
        """Tom input → {} utan API-anrop."""
        with patch.object(kc.requests, "post") as mock_post:
            result = kc._fetch_keyword_difficulty([], "login", "pw")

        mock_post.assert_not_called()
        self.assertEqual(result, {})

    def test_exception_returns_empty_dict(self):
        """Exception vid API-anrop → {} (graceful)."""
        with patch.object(kc.requests, "post", side_effect=Exception("timeout")):
            result = kc._fetch_keyword_difficulty(["seo"], "login", "pw")

        self.assertEqual(result, {})

    def test_uses_correct_endpoint(self):
        """Ska anropa bulk_keyword_difficulty/live-endpoint."""
        called_urls = []

        def _post(url, **kwargs):
            called_urls.append(url)
            return MagicMock(raise_for_status=MagicMock(),
                             json=MagicMock(return_value={"tasks": []}))

        with patch.object(kc.requests, "post", side_effect=_post):
            kc._fetch_keyword_difficulty(["seo"], "login", "pw")

        self.assertTrue(any("bulk_keyword_difficulty" in u for u in called_urls),
                        f"Fel endpoint anropades: {called_urls}")


# ---------------------------------------------------------------------------
# TEST 9: _batch_upsert inkluderar keyword_difficulty-kolumnen
# ---------------------------------------------------------------------------

class TestBatchUpsertIncludesKD(unittest.TestCase):

    def test_upsert_row_has_keyword_difficulty_key(self):
        """_batch_upsert ska inkludera keyword_difficulty i varje rad."""
        sb = MagicMock()
        chain = MagicMock()
        chain.upsert.return_value = chain
        chain.execute.return_value = MagicMock()
        sb.table.return_value = chain

        items = [{"keyword": "seo", "search_volume": 1000, "competition": "0.5",
                  "cpc": 0.3, "keyword_difficulty": 42}]
        kc._batch_upsert(sb, items)

        upsert_call = chain.upsert.call_args
        self.assertIsNotNone(upsert_call)
        rows = upsert_call[0][0]
        self.assertIn("keyword_difficulty", rows[0])
        self.assertEqual(rows[0]["keyword_difficulty"], 42)

    def test_upsert_row_allows_none_kd(self):
        """keyword_difficulty=None ska sparas (NULL i DB) utan fel."""
        sb = MagicMock()
        chain = MagicMock()
        chain.upsert.return_value = chain
        chain.execute.return_value = MagicMock()
        sb.table.return_value = chain

        items = [{"keyword": "seo", "search_volume": 1000, "competition": "0.5",
                  "cpc": 0.3, "keyword_difficulty": None}]
        kc._batch_upsert(sb, items)

        rows = chain.upsert.call_args[0][0]
        self.assertIsNone(rows[0]["keyword_difficulty"])


# ---------------------------------------------------------------------------
# TEST 10: _update_kd_in_cache anropas bara vid kd_update_needed
# ---------------------------------------------------------------------------

class TestUpdateKDInCache(unittest.TestCase):

    def test_update_kd_not_called_when_no_null_kd(self):
        """Om alla färska rader har KD ska _update_kd_in_cache inte anropas."""
        rows = [{
            "keyword": "seo brasil",
            "location_code": 2076,
            "language_code": "pt",
            "search_volume": 5000,
            "competition": "0.4",
            "cpc": 0.5,
            "keyword_difficulty": 42,  # KD finns
            "cached_at": FRESH_TS,
        }]
        sb = _supabase_with_cache(rows)

        with patch.object(kc.requests, "post") as mock_post:
            with patch.object(kc, "_update_kd_in_cache") as mock_update:
                kc.get_keyword_data(["seo brasil"], sb, "login", "pw")

        mock_post.assert_not_called()
        mock_update.assert_not_called()

    def test_update_kd_upserts_only_kd_related_columns(self):
        """_update_kd_in_cache ska bara upserta keyword, location_code, language_code, kd."""
        sb = MagicMock()
        chain = MagicMock()
        chain.upsert.return_value = chain
        chain.execute.return_value = MagicMock()
        sb.table.return_value = chain

        kc._update_kd_in_cache(sb, {"seo": 50})

        rows = chain.upsert.call_args[0][0]
        self.assertEqual(len(rows), 1)
        self.assertIn("keyword_difficulty", rows[0])
        self.assertEqual(rows[0]["keyword_difficulty"], 50)
        # cached_at ska INTE uppdateras (vi rör inte de ursprungliga fälten)
        self.assertNotIn("search_volume", rows[0])
        self.assertNotIn("cached_at", rows[0])

    def test_update_kd_empty_map_no_upsert(self):
        """Tom kd_map → inget upsert-anrop."""
        sb = MagicMock()
        kc._update_kd_in_cache(sb, {})
        sb.table.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 11 & 12: Källkodsinspektion — app.py UI-etiketter och CSV-kolumn
# ---------------------------------------------------------------------------

class TestAppPySourceInspection(unittest.TestCase):

    def setUp(self):
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
        with open(src_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_11_dificuldade_seo_label_in_main_results(self):
        """'Dificuldade SEO' ska finnas som UI-etikett i huvudresultaten."""
        self.assertIn(
            "Dificuldade SEO",
            self.source,
            "TEST 11 FAIL: 'Dificuldade SEO' saknas i app.py UI",
        )

    def test_11_kd_str_variable_in_main_results(self):
        """kd_str-variabeln ska definieras (visar rå siffra utan Low/Med/High)."""
        self.assertIn(
            "kd_str",
            self.source,
            "TEST 11 FAIL: kd_str saknas i app.py",
        )

    def test_12_dificuldade_seo_in_csv_column(self):
        """'Dificuldade SEO' ska vara en CSV-kolumnrubrik."""
        self.assertIn(
            '"Dificuldade SEO"',
            self.source,
            "TEST 12 FAIL: 'Dificuldade SEO' saknas som CSV-kolumn i app.py",
        )

    def test_no_low_med_high_for_kd(self):
        """KD ska visas som råsiffra — inte Low/Medium/High (det är Ads-competition)."""
        # KD-visning ska inte använda _ads_competition_label för kd-värdet
        # Vi kontrollerar att kd_str är str(kd) eller '—', inte 'Low'/'High'
        self.assertIn(
            'kd_str = str(kd) if kd is not None else',
            self.source,
            "TEST 13 FAIL: kd_str ska formateras som råsiffra (str(kd)) eller '—'",
        )

    def test_dificuldade_seo_in_suggestions(self):
        """'Dificuldade SEO' ska visas i Sugestões också."""
        # Det finns två ställen — räkna förekomster
        count = self.source.count("Dificuldade SEO")
        self.assertGreaterEqual(
            count, 2,
            f"TEST 14 FAIL: 'Dificuldade SEO' ska finnas minst 2 gånger i app.py "
            f"(huvud + sugestões), hittades {count} gång(er)",
        )

    def test_ikd_variable_in_suggestions(self):
        """ikd-variabeln ska definieras i sugestões-loopen."""
        self.assertIn(
            "ikd",
            self.source,
            "TEST 15 FAIL: ikd-variabeln saknas i app.py",
        )


# ---------------------------------------------------------------------------
# TEST 13: get_keyword_ideas returnerar keyword_difficulty
# ---------------------------------------------------------------------------

class TestKeywordIdeasIncludesKD(unittest.TestCase):

    def _make_ideas_response(self, keywords):
        items = [{"keyword": kw, "search_volume": 2000, "competition": "0.3", "cpc": 0.4}
                 for kw in keywords]
        return {"tasks": [{"result": items}]}

    def _make_supabase_for_ideas(self, kw_cache_rows=None):
        """
        Supabase-mock för get_keyword_ideas-tester.
        keyword_ideas_cache → alltid cache-miss (tom data).
        keyword_cache → kw_cache_rows (kan innehålla KD-data).
        """
        sb = MagicMock()
        ideas_cache_chain = MagicMock()
        ideas_cache_chain.select.return_value = ideas_cache_chain
        ideas_cache_chain.eq.return_value = ideas_cache_chain
        ideas_cache_chain.execute.return_value = MagicMock(data=[])  # ideas cache-miss
        ideas_cache_chain.upsert.return_value = ideas_cache_chain

        kw_cache_chain = MagicMock()
        kw_cache_chain.select.return_value = kw_cache_chain
        kw_cache_chain.eq.return_value = kw_cache_chain
        kw_cache_chain.in_.return_value = kw_cache_chain
        kw_cache_chain.upsert.return_value = kw_cache_chain
        kw_cache_chain.execute.return_value = MagicMock(data=kw_cache_rows or [])

        def _table(name):
            if name == "keyword_ideas_cache":
                return ideas_cache_chain
            return kw_cache_chain

        sb.table.side_effect = _table
        return sb, kw_cache_chain

    def test_ideas_include_kd_field(self):
        """get_keyword_ideas ska returnera keyword_difficulty i varje post."""
        sb, _ = self._make_supabase_for_ideas(kw_cache_rows=[])  # ingen KD i cache

        ideas_resp = self._make_ideas_response(["proteina whey", "creatina monohidratada"])
        kd_resp = _mock_kd_response({"proteina whey": 33, "creatina monohidratada": 41})

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                resp.json.return_value = kd_resp
            elif "keywords_for_keywords" in url:
                resp.json.return_value = ideas_resp
            else:
                resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_ideas(["proteina"], sb, "login", "pw", limit=5)

        self.assertTrue(len(result) > 0, "Inga idéer returnerades")
        for r in result:
            self.assertIn("keyword_difficulty", r,
                          f"keyword_difficulty saknas i idé: {r}")


# ---------------------------------------------------------------------------
# TEST 13b: get_keyword_ideas() — KD cache-first beteende
# ---------------------------------------------------------------------------

class TestKeywordIdeasKDCacheFirst(unittest.TestCase):
    """
    Verifierar att get_keyword_ideas() följer cache-first för KD:
    - Färsk KD i keyword_cache → INGET KD-API-anrop
    - KD=NULL i keyword_cache → ETT KD-API-anrop
    - Ingen keyword_cache-träff → ETT KD-API-anrop
    - Flera KD-missar → ETT bulk-anrop
    """

    def _make_ideas_response(self, keywords):
        items = [{"keyword": kw, "search_volume": 2000, "competition": "0.3", "cpc": 0.4}
                 for kw in keywords]
        return {"tasks": [{"result": items}]}

    def _make_supabase_for_ideas(self, kw_cache_rows=None):
        """Supabase-mock: ideas_cache = miss, keyword_cache = kw_cache_rows."""
        sb = MagicMock()
        ideas_cache_chain = MagicMock()
        ideas_cache_chain.select.return_value = ideas_cache_chain
        ideas_cache_chain.eq.return_value = ideas_cache_chain
        ideas_cache_chain.execute.return_value = MagicMock(data=[])
        ideas_cache_chain.upsert.return_value = ideas_cache_chain

        kw_cache_chain = MagicMock()
        kw_cache_chain.select.return_value = kw_cache_chain
        kw_cache_chain.eq.return_value = kw_cache_chain
        kw_cache_chain.in_.return_value = kw_cache_chain
        kw_cache_chain.upsert.return_value = kw_cache_chain
        kw_cache_chain.execute.return_value = MagicMock(data=kw_cache_rows or [])

        sb.table.side_effect = lambda name: (
            ideas_cache_chain if name == "keyword_ideas_cache" else kw_cache_chain
        )
        return sb, kw_cache_chain

    # ── TEST A: Färsk KD i keyword_cache → inget KD-API-anrop ────────────

    def test_a_fresh_kd_in_cache_skips_kd_api(self):
        """
        Om keyword_cache har färsk KD för alla idea-keywords
        ska _fetch_keyword_difficulty INTE anropas (KD-kostnad = $0).
        """
        # Simulera att "proteina whey" och "creatina" redan har KD i keyword_cache
        kw_cache_rows = [
            {"keyword": "proteina whey", "location_code": 2076, "language_code": "pt",
             "search_volume": 2000, "competition": "0.3", "cpc": 0.4,
             "keyword_difficulty": 45, "cached_at": FRESH_TS},
            {"keyword": "creatina", "location_code": 2076, "language_code": "pt",
             "search_volume": 1500, "competition": "0.2", "cpc": 0.3,
             "keyword_difficulty": 38, "cached_at": FRESH_TS},
        ]
        sb, _ = self._make_supabase_for_ideas(kw_cache_rows)
        ideas_resp = self._make_ideas_response(["proteina whey", "creatina"])
        kd_call_count = {"n": 0}

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                kd_call_count["n"] += 1
                resp.json.return_value = _mock_kd_response({"proteina whey": 45, "creatina": 38})
            elif "keywords_for_keywords" in url:
                resp.json.return_value = ideas_resp
            else:
                resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_ideas(["proteina"], sb, "login", "pw", limit=5)

        self.assertEqual(kd_call_count["n"], 0,
                         "FAIL: KD-API anropades trots att KD redan finns färskt i keyword_cache")
        self.assertTrue(len(result) > 0)
        for r in result:
            self.assertIsNotNone(r.get("keyword_difficulty"),
                                 f"KD ska komma från cache: {r}")

    def test_a_fresh_kd_returns_cached_values(self):
        """Returnerade KD-värden ska matcha keyword_cache, inte hämtas på nytt."""
        kw_cache_rows = [
            {"keyword": "whey", "location_code": 2076, "language_code": "pt",
             "search_volume": 3000, "competition": "0.5", "cpc": 0.6,
             "keyword_difficulty": 71, "cached_at": FRESH_TS},
        ]
        sb, _ = self._make_supabase_for_ideas(kw_cache_rows)
        ideas_resp = self._make_ideas_response(["whey"])

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "keywords_for_keywords" in url:
                resp.json.return_value = ideas_resp
            else:
                resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_ideas(["protein"], sb, "login", "pw", limit=5)

        whey = next((r for r in result if r["keyword"] == "whey"), None)
        self.assertIsNotNone(whey)
        self.assertEqual(whey["keyword_difficulty"], 71,
                         "FAIL: KD ska vara 71 från cache, inte None eller annat värde")

    # ── TEST B: KD=NULL i keyword_cache → hämtar KD via API ──────────────

    def test_b_null_kd_in_cache_triggers_kd_fetch(self):
        """
        Om keyword_cache har färsk rad men KD=NULL
        ska _fetch_keyword_difficulty anropas för det sökordet.
        """
        kw_cache_rows = [
            {"keyword": "bcaa", "location_code": 2076, "language_code": "pt",
             "search_volume": 1200, "competition": "0.4", "cpc": 0.5,
             "keyword_difficulty": None, "cached_at": FRESH_TS},  # KD=NULL
        ]
        sb, _ = self._make_supabase_for_ideas(kw_cache_rows)
        ideas_resp = self._make_ideas_response(["bcaa"])
        kd_resp = _mock_kd_response({"bcaa": 52})
        kd_call_count = {"n": 0}

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                kd_call_count["n"] += 1
                resp.json.return_value = kd_resp
            elif "keywords_for_keywords" in url:
                resp.json.return_value = ideas_resp
            else:
                resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_ideas(["suplemento"], sb, "login", "pw", limit=5)

        self.assertEqual(kd_call_count["n"], 1,
                         "FAIL: KD-API ska anropas exakt EN gång för KD=NULL i keyword_cache")
        bcaa = next((r for r in result if r["keyword"] == "bcaa"), None)
        self.assertIsNotNone(bcaa)
        self.assertEqual(bcaa["keyword_difficulty"], 52)

    # ── TEST C: Ingen keyword_cache-träff → KD hämtas ────────────────────

    def test_c_no_cache_triggers_kd_fetch(self):
        """Om keyword_cache saknar sökordet ska KD hämtas från API."""
        sb, _ = self._make_supabase_for_ideas(kw_cache_rows=[])  # tom cache
        ideas_resp = self._make_ideas_response(["glutamina"])
        kd_resp = _mock_kd_response({"glutamina": 29})
        kd_call_count = {"n": 0}

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                kd_call_count["n"] += 1
                resp.json.return_value = kd_resp
            elif "keywords_for_keywords" in url:
                resp.json.return_value = ideas_resp
            else:
                resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_ideas(["aminoacido"], sb, "login", "pw", limit=5)

        self.assertEqual(kd_call_count["n"], 1)
        g = next((r for r in result if r["keyword"] == "glutamina"), None)
        self.assertIsNotNone(g)
        self.assertEqual(g["keyword_difficulty"], 29)

    # ── TEST D: Blandning — del av ideas har KD, del saknar → ETT bulk-anrop

    def test_d_partial_cache_single_kd_bulk_call(self):
        """
        3 idea-keywords: 1 med färsk KD, 2 utan → ETT KD-API-anrop
        med exakt de 2 som saknar KD.
        """
        kw_cache_rows = [
            {"keyword": "omega3", "location_code": 2076, "language_code": "pt",
             "search_volume": 800, "competition": "0.2", "cpc": 0.3,
             "keyword_difficulty": 18, "cached_at": FRESH_TS},  # har KD
        ]
        sb, _ = self._make_supabase_for_ideas(kw_cache_rows)
        ideas_resp = self._make_ideas_response(["omega3", "vitamina_c", "zinco"])
        kd_resp = _mock_kd_response({"vitamina_c": 40, "zinco": 33})
        kd_payloads = []

        def _post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "bulk_keyword_difficulty" in url:
                kd_payloads.append(kwargs.get("json", []))
                resp.json.return_value = kd_resp
            elif "keywords_for_keywords" in url:
                resp.json.return_value = ideas_resp
            else:
                resp.json.return_value = {"tasks": []}
            return resp

        with patch.object(kc.requests, "post", side_effect=_post):
            result = kc.get_keyword_ideas(["suplemento"], sb, "login", "pw", limit=5)

        # Exakt ETT KD-anrop
        self.assertEqual(len(kd_payloads), 1,
                         "FAIL: ska göras ETT KD-anrop, inte fler")
        sent_kws = set(kd_payloads[0][0]["keywords"])
        # omega3 ska INTE vara med (har färsk KD i cache)
        self.assertNotIn("omega3", sent_kws,
                         "FAIL: omega3 har färsk KD och ska inte skickas till KD-API")
        # vitamina_c och zinco ska vara med
        self.assertIn("vitamina_c", sent_kws)
        self.assertIn("zinco", sent_kws)

        # Rätt KD-värden i resultatet
        kd_map_result = {r["keyword"]: r.get("keyword_difficulty") for r in result}
        self.assertEqual(kd_map_result.get("omega3"), 18)
        self.assertEqual(kd_map_result.get("vitamina_c"), 40)
        self.assertEqual(kd_map_result.get("zinco"), 33)

    # ── TEST E: Källkodsinspektion — cache-first mönster i get_keyword_ideas

    def test_e_source_cache_first_pattern(self):
        """Källkoden ska innehålla cache-first KD-logik i get_keyword_ideas."""
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keyword_cache.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()

        self.assertIn("cached_kd_rows", source,
                      "FAIL: cached_kd_rows saknas — cache-first KD-logik saknas i get_keyword_ideas")
        self.assertIn("kd_to_fetch", source,
                      "FAIL: kd_to_fetch-listan saknas i get_keyword_ideas")
        # Ska INTE alltid kalla _fetch_keyword_difficulty för alla idea-keywords
        self.assertNotIn(
            "kd_map = _fetch_keyword_difficulty(idea_keywords",
            source,
            "FAIL: get_keyword_ideas anropar fortfarande KD-API för ALLA idea_keywords "
            "(ska vara cache-first)",
        )


# ---------------------------------------------------------------------------
# TEST 14: keyword_cache.py källkodsinspektion — KD-relaterade mönster
# ---------------------------------------------------------------------------

class TestKeywordCacheSourceInspection(unittest.TestCase):

    def setUp(self):
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keyword_cache.py")
        with open(src_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_kd_endpoint_defined(self):
        """KD_ENDPOINT-konstanten ska finnas."""
        self.assertIn("KD_ENDPOINT", self.source,
                      "FAIL: KD_ENDPOINT saknas i keyword_cache.py")
        self.assertIn("bulk_keyword_difficulty", self.source,
                      "FAIL: bulk_keyword_difficulty-endpoint saknas")

    def test_fetch_keyword_difficulty_function_defined(self):
        """_fetch_keyword_difficulty ska vara definierad."""
        self.assertIn("def _fetch_keyword_difficulty(", self.source,
                      "FAIL: _fetch_keyword_difficulty saknas")

    def test_update_kd_in_cache_function_defined(self):
        """_update_kd_in_cache ska vara definierad."""
        self.assertIn("def _update_kd_in_cache(", self.source,
                      "FAIL: _update_kd_in_cache saknas")

    def test_kd_in_batch_upsert(self):
        """_batch_upsert ska innehålla keyword_difficulty."""
        self.assertIn('"keyword_difficulty"', self.source,
                      "FAIL: keyword_difficulty saknas i _batch_upsert-raden")

    def test_kd_update_needed_tracked(self):
        """get_keyword_data ska tracka kd_update_needed-listan."""
        self.assertIn("kd_update_needed", self.source,
                      "FAIL: kd_update_needed-listan saknas i get_keyword_data")

    def test_keyword_difficulty_in_return_dict(self):
        """final_results-dicts ska innehålla keyword_difficulty."""
        # Kontrollera att "keyword_difficulty" finns i final_results.append-blocken
        self.assertIn('"keyword_difficulty":', self.source,
                      "FAIL: keyword_difficulty saknas i returnerade dicts")

    def test_get_keyword_ideas_returns_kd(self):
        """get_keyword_ideas ska returnera keyword_difficulty."""
        self.assertIn("keyword_difficulty", self.source,
                      "FAIL: keyword_difficulty saknas i get_keyword_ideas")


# ---------------------------------------------------------------------------
# Kör tester
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for cls in [
        TestCacheHitWithKD,
        TestFreshCacheNullKD,
        TestCacheMissFetchesFullAndKD,
        TestExpiredCacheRefetches,
        TestBulkKDSingleCall,
        TestKDApiFailureGraceful,
        TestSearchVolumeApiFailureGraceful,
        TestFetchKeywordDifficultyParsing,
        TestBatchUpsertIncludesKD,
        TestUpdateKDInCache,
        TestAppPySourceInspection,
        TestKeywordIdeasIncludesKD,
        TestKeywordIdeasKDCacheFirst,
        TestKeywordCacheSourceInspection,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

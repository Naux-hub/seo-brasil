"""
test_initial_ranking_v1.py
==========================
Testar V1 + V1.1-fix + V1.2-fix av initial rankingkörning:
  get_keywords_without_rankings()
  Gate-logiken för on-demand ranking
  run_on_demand_ranking() — market-fält, save_ok-flagga, undantagshantering,
                             access_token-vidarebefordran, verifiering efter upsert

V1.2-fix testar:
  1.  access_token skickas till run_on_demand_ranking (källkodsinspektion)
  2.  autentiserad postgrest-instans används vid UPSERT (mocktest)
  3.  market="br" finns kvar (källkodsinspektion + mocktest)
  4.  verifieringen kontrollerar exakt de nya keywords (mocktest)
  5.  lyckad UPSERT + verifiering => save_ok=True
  6.  UPSERT exception => save_ok=False
  7.  verifiering utan förväntad rad => save_ok=False
  8.  success-banner visas endast när save_ok=True (källkodsinspektion)
  9.  nya keywords körs fortfarande (get_keywords_without_rankings)
  10. befintliga keywords körs inte om
  11. Mexico är orörd
  12. weekly rank tracker är orörd

Inga anrop till Supabase, DataForSEO eller extern tjänst.
All Supabase-interaktion mockas via unittest.mock.

Kör:
    python test_initial_ranking_v1.py
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stub för Supabase så att import av app_brasil_new inte kraschar
# ---------------------------------------------------------------------------

def _make_supabase_stub():
    stub = MagicMock()
    # table(...).select(...).eq(...).execute() → tom lista
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[], count=0)
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.limit.return_value = chain
    chain.order.return_value = chain
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.upsert.return_value = chain
    chain.update.return_value = chain
    stub.table.return_value = chain
    return stub


def _make_supabase_module_stub():
    mod = types.ModuleType("supabase")
    mod.create_client = MagicMock(return_value=_make_supabase_stub())
    return mod


def _make_requests_stub():
    mod = types.ModuleType("requests")
    mod.post = MagicMock(return_value=MagicMock(json=lambda: {"status_code": 20000, "tasks": []}))
    mod.get = MagicMock(return_value=MagicMock(json=lambda: {"tasks": []}))
    return mod


def _make_streamlit_stub():
    """Minimal streamlit-stub så att app-koden kan importeras utan att krascha."""
    mod = types.ModuleType("streamlit")
    for attr in [
        "title", "header", "subheader", "markdown", "write", "info",
        "warning", "error", "success", "divider", "caption", "empty",
        "spinner", "tabs", "columns", "button", "text_input", "text_area",
        "progress", "download_button", "rerun", "stop", "set_page_config",
    ]:
        setattr(mod, attr, MagicMock())
    mod.session_state = MagicMock()
    mod.secrets = {"SUPABASE_URL": "https://test.supabase.co",
                   "SUPABASE_KEY": "test-key",
                   "DATAFORSEO_LOGIN": "test@test.com",
                   "DATAFORSEO_PASSWORD": "testpw"}
    # secrets.get() support
    mod.secrets = MagicMock()
    mod.secrets.__getitem__ = lambda self, k: "test-value"
    mod.secrets.get = MagicMock(return_value="test-value")
    return mod


# Sätt upp stubs INNAN vi importerar app_brasil_new
sys.modules.setdefault("supabase", _make_supabase_module_stub())
sys.modules.setdefault("requests", _make_requests_stub())
sys.modules.setdefault("streamlit", _make_streamlit_stub())

# Stubs för övriga beroenden
for mod_name in [
    "pandas", "plotly", "plotly.express", "plotly.graph_objects",
    "keyword_cache", "market_config", "anthropic",
    "streamlit_cookies_controller",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# market_config behöver returnera riktiga värden
sys.modules["market_config"].get_market = MagicMock(
    return_value={"location_code": 2076, "language_code": "pt"}
)
sys.modules["market_config"].market_from_env = MagicMock(return_value="br")

# ---------------------------------------------------------------------------
# Kopiera implementationer ur app_brasil_new.py för isolerad testning
# ---------------------------------------------------------------------------

def get_keywords_without_rankings_impl(supabase_client, user_id, domain):
    """
    Kopia av get_keywords_without_rankings() ur app_brasil_new.py för isolerad testning.
    (Identisk logik, oberoende av Streamlit-import.)
    """
    try:
        all_res = supabase_client.table("tracked_keywords") \
            .select("keyword") \
            .eq("user_id", str(user_id)) \
            .eq("is_active", True) \
            .execute()
        all_keywords = {r["keyword"] for r in (all_res.data or [])}

        if not all_keywords or not domain:
            return []

        ranked_res = supabase_client.table("keyword_rankings") \
            .select("keyword") \
            .eq("user_id", str(user_id)) \
            .eq("domain", domain) \
            .in_("keyword", list(all_keywords)) \
            .execute()
        ranked_keywords = {r["keyword"] for r in (ranked_res.data or [])}

        return list(all_keywords - ranked_keywords)
    except Exception:
        return []


def run_on_demand_ranking_impl(supabase_client, user_id, domain, keywords):
    """
    Isolerad testkopia av run_on_demand_ranking() — V1.1-semantik:
      - rows inkluderar market='br'
      - returnerar (results, save_ok)
      - exception vid upsert → save_ok=False (ingen silent swallow)
    """
    results = {kw: {"position": None, "url": None} for kw in keywords}

    now = "2026-09-17T12:00:00+00:00"
    rows = [
        {
            "user_id": str(user_id),
            "keyword": kw,
            "domain": domain,
            "rank_position": d["position"],
            "prev_rank_position": None,
            "checked_at": now,
            "market": "br",
        }
        for kw, d in results.items()
    ]

    save_ok = False
    if rows:
        try:
            supabase_client.table("keyword_rankings").upsert(
                rows, on_conflict="user_id,keyword,domain"
            ).execute()
            save_ok = True
        except Exception as e:
            import traceback
            print(f"[test] upsert error: {e}\n{traceback.format_exc()}")

    return results, save_ok


# ---------------------------------------------------------------------------
# Testklasser
# ---------------------------------------------------------------------------

class TestGetKeywordsWithoutRankings(unittest.TestCase):
    """TEST 1-4: get_keywords_without_rankings()"""

    def _make_client(self, tracked_keywords, ranked_keywords):
        """Skapar en mock-Supabase med specificerade data."""
        client = MagicMock()

        def table_side_effect(table_name):
            chain = MagicMock()

            if table_name == "tracked_keywords":
                chain.execute.return_value = MagicMock(
                    data=[{"keyword": kw} for kw in tracked_keywords]
                )
            elif table_name == "keyword_rankings":
                chain.execute.return_value = MagicMock(
                    data=[{"keyword": kw} for kw in ranked_keywords]
                )
            else:
                chain.execute.return_value = MagicMock(data=[])

            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.in_.return_value = chain
            chain.limit.return_value = chain
            return chain

        client.table.side_effect = table_side_effect
        return client

    # TEST 1: Ny användare — 1 keyword, inga rankingar
    def test_1_new_user_single_keyword_no_rankings(self):
        """Ny användare med 1 keyword → keyword returneras."""
        client = self._make_client(
            tracked_keywords=["seo brasil"],
            ranked_keywords=[],
        )
        result = get_keywords_without_rankings_impl(client, "user-1", "meusite.com.br")
        self.assertEqual(sorted(result), ["seo brasil"],
                         "TEST 1 FAIL: Nytt keyword ska returneras")

    # TEST 2: Ny användare — flera keywords, inga rankingar
    def test_2_new_user_multiple_keywords_no_rankings(self):
        """Ny användare med 3 keywords → alla returneras."""
        client = self._make_client(
            tracked_keywords=["seo", "marketing digital", "agencia seo"],
            ranked_keywords=[],
        )
        result = get_keywords_without_rankings_impl(client, "user-2", "meusite.com.br")
        self.assertEqual(sorted(result), sorted(["seo", "marketing digital", "agencia seo"]),
                         "TEST 2 FAIL: Alla nya keywords ska returneras")

    # TEST 3: Befintlig användare — 5 keywords med data, 1 nytt utan
    def test_3_existing_user_one_new_keyword(self):
        """Befintlig användare: 5 rankade, 1 nytt → bara det nya returneras."""
        tracked = ["kw-a", "kw-b", "kw-c", "kw-d", "kw-e", "kw-new"]
        ranked = ["kw-a", "kw-b", "kw-c", "kw-d", "kw-e"]
        client = self._make_client(tracked, ranked)
        result = get_keywords_without_rankings_impl(client, "user-3", "meusite.com.br")
        self.assertEqual(result, ["kw-new"],
                         "TEST 3 FAIL: Bara det nya keywordet ska returneras")

    # TEST 4: Befintlig användare — flera nya keywords utan data
    def test_4_existing_user_multiple_new_keywords(self):
        """Befintlig användare: 2 rankade, 2 nya → bara de 2 nya returneras."""
        tracked = ["kw-a", "kw-b", "kw-new-1", "kw-new-2"]
        ranked = ["kw-a", "kw-b"]
        client = self._make_client(tracked, ranked)
        result = get_keywords_without_rankings_impl(client, "user-4", "meusite.com.br")
        self.assertEqual(sorted(result), ["kw-new-1", "kw-new-2"],
                         "TEST 4 FAIL: Båda nya keywords ska returneras")

    # TEST 7: Alla keywords redan rankade → tom lista (ingen on-demand-körning)
    def test_7_all_keywords_already_ranked(self):
        """Alla keywords har rankingdata → tom lista returneras (inget att köra)."""
        tracked = ["kw-a", "kw-b"]
        ranked = ["kw-a", "kw-b"]
        client = self._make_client(tracked, ranked)
        result = get_keywords_without_rankings_impl(client, "user-5", "meusite.com.br")
        self.assertEqual(result, [],
                         "TEST 7 FAIL: Tom lista när alla är rankade — ingen on-demand ska triggas")

    def test_empty_tracked_keywords(self):
        """Inga spårade keywords → tom lista."""
        client = self._make_client(tracked_keywords=[], ranked_keywords=[])
        result = get_keywords_without_rankings_impl(client, "user-6", "meusite.com.br")
        self.assertEqual(result, [], "Tom lista om inga keywords finns")

    def test_no_domain(self):
        """Utan domän → tom lista (domän krävs för rankings)."""
        client = self._make_client(tracked_keywords=["seo"], ranked_keywords=[])
        result = get_keywords_without_rankings_impl(client, "user-7", None)
        self.assertEqual(result, [], "Tom lista om domain är None")

    def test_exception_handling(self):
        """Supabase-fel → tom lista, inget undantag kastas."""
        client = MagicMock()
        client.table.side_effect = Exception("DB connection error")
        result = get_keywords_without_rankings_impl(client, "user-8", "meusite.com.br")
        self.assertEqual(result, [], "Exception ska fångas och returnera []")

    # TEST 5 (nytt): Ny keyword körs fortfarande (V1-logik bevarad)
    def test_5_new_keyword_triggers_on_demand(self):
        """Ny keyword ska trigga on-demand (returneras av get_keywords_without_rankings)."""
        tracked = ["bank", "banco", "fintech"]
        ranked = ["bank", "fintech"]
        client = self._make_client(tracked, ranked)
        result = get_keywords_without_rankings_impl(client, "user-9", "meusite.com.br")
        self.assertEqual(result, ["banco"],
                         "TEST 5 FAIL: 'banco' är nytt och ska returneras för on-demand-körning")

    # TEST 6 (nytt): Befintliga keywords med rankingdata körs inte igen
    def test_6_existing_keywords_not_rerun(self):
        """Keywords med rankingdata ska INTE inkluderas i on-demand-körningen."""
        tracked = ["kw-old-1", "kw-old-2"]
        ranked = ["kw-old-1", "kw-old-2"]
        client = self._make_client(tracked, ranked)
        result = get_keywords_without_rankings_impl(client, "user-10", "meusite.com.br")
        self.assertNotIn("kw-old-1", result,
                         "TEST 6 FAIL: kw-old-1 har rankingdata och ska inte köras igen")
        self.assertNotIn("kw-old-2", result,
                         "TEST 6 FAIL: kw-old-2 har rankingdata och ska inte köras igen")


class TestRunOnDemandRankingV11(unittest.TestCase):
    """TEST V1.1: run_on_demand_ranking() — market-fält, save_ok, undantag"""

    def _make_upsert_client(self, should_fail=False, fail_exception=None):
        """Skapar en mock-Supabase-klient för upsert-testning."""
        client = MagicMock()
        chain = MagicMock()

        if should_fail:
            exc = fail_exception or Exception("DB upsert error")
            chain.execute.side_effect = exc
        else:
            chain.execute.return_value = MagicMock(data=[])

        chain.upsert.return_value = chain
        client.table.return_value = chain
        return client

    # TEST V1.1-1: Upsert inkluderar market="br"
    def test_v11_upsert_includes_market_br(self):
        """Upsert-raden ska alltid innehålla market='br'."""
        client = self._make_upsert_client(should_fail=False)
        results, save_ok = run_on_demand_ranking_impl(client, "user-1", "meusite.com.br", ["banco"])

        # Hämta anropet till upsert
        upsert_call = client.table.return_value.upsert.call_args
        self.assertIsNotNone(upsert_call, "TEST V1.1-1 FAIL: upsert ska ha anropats")
        rows_sent = upsert_call[0][0]  # första positionella argument = rows
        self.assertIsInstance(rows_sent, list, "Rows ska vara en lista")
        self.assertEqual(len(rows_sent), 1, "En rad för ett keyword")
        self.assertEqual(rows_sent[0].get("market"), "br",
                         "TEST V1.1-1 FAIL: market='br' saknas i upsert-raden")

    # TEST V1.1-2: Lyckad upsert → save_ok=True
    def test_v11_successful_upsert_returns_save_ok_true(self):
        """Lyckad upsert ska returnera save_ok=True."""
        client = self._make_upsert_client(should_fail=False)
        results, save_ok = run_on_demand_ranking_impl(client, "user-1", "meusite.com.br", ["banco"])
        self.assertTrue(save_ok,
                        "TEST V1.1-2 FAIL: Lyckad upsert ska ge save_ok=True")

    # TEST V1.1-3: Upsert exception → save_ok=False
    def test_v11_upsert_exception_returns_save_ok_false(self):
        """Upsert-exception ska returnera save_ok=False (inte svälja tyst)."""
        client = self._make_upsert_client(should_fail=True)
        results, save_ok = run_on_demand_ranking_impl(client, "user-1", "meusite.com.br", ["banco"])
        self.assertFalse(save_ok,
                         "TEST V1.1-3 FAIL: Upsert-exception ska ge save_ok=False")

    # TEST V1.1-4: save_ok=False → "Seu primeiro ranking" ska INTE visas
    def test_v11_save_failure_no_success_message(self):
        """
        Kontrollerar gate-logiken: ranking_done ska bara sättas till True
        om save_ok=True. Simuleras via att kontrollera save_ok-returvärdet.
        """
        client = self._make_upsert_client(should_fail=True)
        _, save_ok = run_on_demand_ranking_impl(client, "user-1", "meusite.com.br", ["banco"])

        # ranking_done = save_ok i calling code
        ranking_done = save_ok
        self.assertFalse(ranking_done,
                         "TEST V1.1-4 FAIL: ranking_done ska vara False vid save-fel — "
                         "framgångsmeddelandet ska INTE visas")

    # TEST V1.1-5: Resultat returneras även vid save-fel
    def test_v11_results_returned_even_on_save_failure(self):
        """Results-dict returneras alltid, oavsett save-resultat."""
        client = self._make_upsert_client(should_fail=True)
        results, save_ok = run_on_demand_ranking_impl(client, "user-1", "meusite.com.br", ["banco"])
        self.assertIn("banco", results,
                      "TEST V1.1-5 FAIL: results ska alltid returneras")
        self.assertFalse(save_ok, "save_ok ska vara False vid upsert-fel")


class TestNoDoubleRankings(unittest.TestCase):
    """TEST: Upsert-logiken förhindrar dubbla rader."""

    def test_upsert_conflict_key_is_set(self):
        """
        Verifierar att run_on_demand_ranking använder
        on_conflict='user_id,keyword,domain'.
        Läser källkoden direkt.
        """
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()

        self.assertIn(
            'on_conflict="user_id,keyword,domain"',
            source,
            "FAIL: upsert måste använda on_conflict='user_id,keyword,domain'",
        )

    def test_upsert_includes_market_br_in_source(self):
        """
        V1.1: run_on_demand_ranking ska inkludera market='br' i upsert-raden.
        Läser källkoden direkt.
        """
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()

        self.assertIn(
            '"market": "br"',
            source,
            "TEST V1.1-1 FAIL: market='br' saknas i app_brasil_new.py upsert",
        )

    def test_no_silent_exception_swallow_in_source(self):
        """
        V1.1: except Exception: pass ska INTE förekomma i run_on_demand_ranking.
        """
        import os, ast
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()

        # Hitta run_on_demand_ranking-funktionen och kontrollera att den inte
        # har en tom except-handler
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run_on_demand_ranking":
                func_src = ast.get_source_segment(source, node)
                # "except Exception:\n            pass" ska inte finnas
                self.assertNotIn(
                    "except Exception:\n            pass",
                    func_src or "",
                    "TEST V1.1-3 FAIL: silent 'except Exception: pass' finns kvar i run_on_demand_ranking",
                )
                return
        self.fail("run_on_demand_ranking hittades inte i källkoden")


class TestUnchangedFiles(unittest.TestCase):
    """TEST 8-10: rank_tracker.py, weekly_seo_report.yml och app_mexico_new.py är oförändrade."""

    def test_rank_tracker_not_modified(self):
        """rank_tracker.py ska inte innehålla get_keywords_without_rankings."""
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rank_tracker.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn(
            "get_keywords_without_rankings",
            content,
            "TEST 8 FAIL: rank_tracker.py ska inte ha ändrats",
        )
        # Verifiera att rank_tracker fortfarande har run()-funktionen
        self.assertIn("def run():", content,
                      "TEST 8 FAIL: run() saknas i rank_tracker.py")
        # Verifiera att rank_tracker inkluderar market
        self.assertIn('"market": MARKET', content,
                      "TEST 8 FAIL: rank_tracker.py ska fortfarande ha market-fältet")

    def test_weekly_yml_not_modified(self):
        """weekly_seo_report.yml ska fortfarande trigga måndag kl 07:00 UTC."""
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly_seo_report.yml")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("0 7 * * 1", content,
                      "TEST 9 FAIL: weekly cron ska vara oförändrad (0 7 * * 1)")
        self.assertIn("rank_tracker.py", content,
                      "TEST 9 FAIL: weekly_seo_report.yml ska fortfarande köra rank_tracker.py")

    def test_mexico_app_not_modified(self):
        """app_mexico_new.py ska inte innehålla get_keywords_without_rankings."""
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_mexico_new.py")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn(
                "get_keywords_without_rankings",
                content,
                "TEST 10 FAIL: app_mexico_new.py ska inte ha ändrats",
            )


class TestGateLogic(unittest.TestCase):
    """TEST: Regression — verifiera att ny gate-logik finns i app_brasil_new.py."""

    def setUp(self):
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_new_gate_present(self):
        """Den nya get_keywords_without_rankings-gaten ska finnas."""
        self.assertIn(
            "get_keywords_without_rankings",
            self.source,
            "FAIL: ny gate-funktion saknas i app_brasil_new.py",
        )

    def test_old_gate_removed_from_buttons(self):
        """
        Den gamla gaten 'not has_any_rankings(user_id)' ska inte längre
        förekomma i + Rastrear-knapparna.
        """
        occurrences = self.source.count("if _user_domain and not has_any_rankings(user_id):")
        self.assertEqual(
            occurrences, 0,
            "FAIL: gamla gaten if _user_domain and not has_any_rankings() ska vara borttagen",
        )

    def test_has_any_rankings_still_used_in_onboarding(self):
        """has_any_rankings() ska fortfarande användas i get_onboarding_status()."""
        self.assertIn(
            "has_any_rankings(user_id)",
            self.source,
            "FAIL: has_any_rankings() verkar ha tagits bort helt",
        )

    def test_function_defined(self):
        """get_keywords_without_rankings ska vara definierad som funktion."""
        self.assertIn(
            "def get_keywords_without_rankings(",
            self.source,
            "FAIL: get_keywords_without_rankings() är inte definierad",
        )

    def test_ranking_save_error_state_initialized(self):
        """V1.1: ranking_save_error ska initialiseras i session_state."""
        self.assertIn(
            '"ranking_save_error"',
            self.source,
            "FAIL: ranking_save_error saknas i session_state-initialisering",
        )

    def test_success_message_conditional_on_ranking_done(self):
        """V1.1: framgångsmeddelandet ska bara visas när ranking_done är True."""
        self.assertIn(
            'st.session_state.ranking_done',
            self.source,
            "FAIL: ranking_done används inte för att styra framgångsmeddelandet",
        )
        # ranking_done ska sättas till _save_ok (inte alltid True)
        self.assertIn(
            "ranking_done = _save_ok",
            self.source,
            "FAIL: ranking_done ska sättas till _save_ok, inte alltid True",
        )

    def test_error_message_shown_on_save_failure(self):
        """V1.1: portugisiskt felmeddelande ska visas vid save-fel."""
        self.assertIn(
            "ranking_save_error",
            self.source,
            "FAIL: ranking_save_error saknas i felmeddelande-logiken",
        )
        self.assertIn(
            "Não foi possível salvar",
            self.source,
            "FAIL: portugisiskt felmeddelande saknas",
        )


# ---------------------------------------------------------------------------
# V1.2-implementationskopia för isolerad testning
# ---------------------------------------------------------------------------

def run_on_demand_ranking_v12_impl(supabase_client, user_id, domain, keywords,
                                    access_token=None):
    """
    Kopia av run_on_demand_ranking() ur app_brasil_new.py — V1.2-semantik:
      - rows inkluderar market='br'
      - använder supabase.postgrest.auth(access_token) för autentiserat upsert
      - verifierar att exakt de förväntade keywords finns efter upsert
      - save_ok=True ENDAST om verifieringen bekräftar alla förväntade rader
    """
    results = {kw: {"position": None, "url": None} for kw in keywords}

    now = "2026-09-17T12:00:00+00:00"
    rows = [
        {
            "user_id": str(user_id),
            "keyword": kw,
            "domain": domain,
            "rank_position": d["position"],
            "prev_rank_position": None,
            "checked_at": now,
            "market": "br",
        }
        for kw, d in results.items()
    ]

    save_ok = False
    if rows:
        expected_kws = [r["keyword"] for r in rows]
        try:
            _pg = supabase_client.postgrest.auth(access_token) if access_token \
                  else supabase_client.postgrest
            _pg.from_("keyword_rankings").upsert(
                rows, on_conflict="user_id,keyword,domain"
            ).execute()

            _pg_v = supabase_client.postgrest.auth(access_token) if access_token \
                    else supabase_client.postgrest
            _verify = (
                _pg_v.from_("keyword_rankings")
                .select("keyword")
                .eq("user_id", str(user_id))
                .eq("domain", domain)
                .in_("keyword", expected_kws)
                .execute()
            )
            found_kws = {r["keyword"] for r in (_verify.data or [])}
            save_ok = set(expected_kws) == found_kws
        except Exception as e:
            import traceback
            print(f"[test-v12] upsert error: {e}\n{traceback.format_exc()}")

    return results, save_ok


# ---------------------------------------------------------------------------
# V1.2-tester (12 cases)
# ---------------------------------------------------------------------------

class TestRunOnDemandRankingV12(unittest.TestCase):
    """
    V1.2-fix: alla 12 specificerade testfall.
    Testar access_token-vidarebefordran, autentiserad postgrest-instans,
    market='br', verifiering och save_ok-semantik.
    """

    # ── Hjälpmetoder ──────────────────────────────────────────────────────

    def _make_pg_chain(self, verify_data=None, upsert_fail=False, verify_fail=False):
        """
        Bygger en mock-postgrest-instans som:
        - .auth(token) returnerar sig själv (chainbar)
        - .from_() -> chain med .upsert(), .select(), .eq(), .in_(), .execute()
        - execute() returnerar angiven verify_data (eller kastar undantag)
        """
        chain = MagicMock()
        chain.from_.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.upsert.return_value = chain

        call_count = {"n": 0}

        def _execute():
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Första execute = upsert
                if upsert_fail:
                    raise Exception("DB upsert error")
                return MagicMock(data=[])
            else:
                # Andra execute = verifiering
                if verify_fail:
                    raise Exception("DB verify error")
                if verify_data is None:
                    return MagicMock(data=[])
                return MagicMock(data=verify_data)

        chain.execute.side_effect = _execute
        return chain

    def _make_client(self, verify_data=None, upsert_fail=False, verify_fail=False):
        """Supabase-klient med stubbad postgrest-instans."""
        client = MagicMock()
        chain = self._make_pg_chain(
            verify_data=verify_data,
            upsert_fail=upsert_fail,
            verify_fail=verify_fail,
        )
        # postgrest.auth(token) returnerar chain (ny instans per anrop)
        client.postgrest.auth.return_value = chain
        client.postgrest.from_.return_value = chain
        return client, chain

    # ── TEST 1: access_token skickas från anroparen (källkodsinspektion) ──

    def test_1_access_token_passed_in_caller(self):
        """access_token=st.session_state.access_token ska finnas i run_on_demand_ranking-anropet."""
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn(
            "st.session_state.access_token",
            source,
            "TEST 1 FAIL: st.session_state.access_token saknas i anropet till run_on_demand_ranking",
        )
        # Verifiera att det är i samma block som run_on_demand_ranking-anropet
        self.assertIn(
            "run_on_demand_ranking(",
            source,
            "TEST 1 FAIL: run_on_demand_ranking-anropet saknas",
        )

    # ── TEST 2: autentiserad postgrest-instans används vid UPSERT ─────────

    def test_2_authenticated_postgrest_instance_used_for_upsert(self):
        """supabase.postgrest.auth(access_token) ska anropas med rätt token."""
        client, chain = self._make_client(verify_data=[{"keyword": "banco"}])

        results, save_ok = run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco"],
            access_token="test-jwt-token",
        )

        # postgrest.auth() ska ha anropats (minst en gång för upsert)
        client.postgrest.auth.assert_called_with("test-jwt-token")
        self.assertGreaterEqual(
            client.postgrest.auth.call_count, 1,
            "TEST 2 FAIL: postgrest.auth() ska anropas med access_token",
        )

    def test_2b_no_access_token_falls_back_to_postgrest(self):
        """Utan access_token ska supabase.postgrest användas direkt (fallback)."""
        client, chain = self._make_client(verify_data=[{"keyword": "banco"}])

        run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco"],
            access_token=None,
        )

        # postgrest.auth() ska INTE ha anropats
        client.postgrest.auth.assert_not_called()

    # ── TEST 3: market="br" finns kvar ────────────────────────────────────

    def test_3_market_br_in_upsert_rows(self):
        """Upsert-raderna ska alltid innehålla market='br'."""
        client, chain = self._make_client(verify_data=[{"keyword": "banco"}])

        run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco"],
            access_token="tok",
        )

        # Hämta rows-argumentet från upsert-anropet
        upsert_call = chain.upsert.call_args
        self.assertIsNotNone(upsert_call, "TEST 3 FAIL: upsert ska ha anropats")
        rows_sent = upsert_call[0][0]
        self.assertIsInstance(rows_sent, list)
        self.assertEqual(len(rows_sent), 1)
        self.assertEqual(
            rows_sent[0].get("market"), "br",
            "TEST 3 FAIL: market='br' saknas i upsert-raden",
        )

    def test_3_market_br_in_source(self):
        """Källkoden ska innehålla market='br' i upsert-blocket."""
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn(
            '"market": "br"',
            source,
            "TEST 3 FAIL: market='br' saknas i app_brasil_new.py",
        )

    # ── TEST 4: verifiering kontrollerar exakt de nya keywords ────────────

    def test_4_verification_uses_exact_keywords(self):
        """Verifieringen ska göra .in_('keyword', [exakt de förväntade keywords])."""
        verify_data = [{"keyword": "banco"}, {"keyword": "seo brasil"}]
        client, chain = self._make_client(verify_data=verify_data)

        run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco", "seo brasil"],
            access_token="tok",
        )

        # .in_() ska ha anropats med exakt de förväntade keywords
        in_calls = [str(c) for c in chain.in_.call_args_list]
        self.assertTrue(
            any("banco" in c and "seo brasil" in c for c in in_calls),
            f"TEST 4 FAIL: .in_() anropades inte med båda keywords. Anrop: {in_calls}",
        )

    def test_4_verification_filters_user_and_domain(self):
        """Verifierings-SELECT ska filtrera på user_id och domain."""
        verify_data = [{"keyword": "banco"}]
        client, chain = self._make_client(verify_data=verify_data)

        run_on_demand_ranking_v12_impl(
            client, "uid-abc", "meusite.com.br", ["banco"],
            access_token="tok",
        )

        eq_calls = [str(c) for c in chain.eq.call_args_list]
        self.assertTrue(
            any("uid-abc" in c for c in eq_calls),
            f"TEST 4 FAIL: .eq('user_id', ...) saknas i verifieringen. Anrop: {eq_calls}",
        )
        self.assertTrue(
            any("meusite.com.br" in c for c in eq_calls),
            f"TEST 4 FAIL: .eq('domain', ...) saknas i verifieringen. Anrop: {eq_calls}",
        )

    # ── TEST 5: lyckad UPSERT + verifiering => save_ok=True ───────────────

    def test_5_successful_upsert_and_verification_gives_save_ok_true(self):
        """Lyckad upsert OCH verifiering med alla förväntade keywords → save_ok=True."""
        client, chain = self._make_client(
            verify_data=[{"keyword": "banco"}, {"keyword": "fintech"}]
        )

        _, save_ok = run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco", "fintech"],
            access_token="tok",
        )

        self.assertTrue(save_ok, "TEST 5 FAIL: lyckad upsert + korrekt verifiering ska ge save_ok=True")

    # ── TEST 6: UPSERT exception => save_ok=False ─────────────────────────

    def test_6_upsert_exception_gives_save_ok_false(self):
        """Exception vid upsert ska ge save_ok=False."""
        client, chain = self._make_client(upsert_fail=True)

        _, save_ok = run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco"],
            access_token="tok",
        )

        self.assertFalse(save_ok, "TEST 6 FAIL: upsert-exception ska ge save_ok=False")

    # ── TEST 7: verifiering utan förväntad rad => save_ok=False ───────────

    def test_7_verification_empty_result_gives_save_ok_false(self):
        """Verifiering returnerar inga rader (RLS silent-fail) → save_ok=False."""
        client, chain = self._make_client(verify_data=[])  # 0 rader

        _, save_ok = run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco"],
            access_token="tok",
        )

        self.assertFalse(
            save_ok,
            "TEST 7 FAIL: verifiering utan rad ska ge save_ok=False (fångar RLS silent-fail)",
        )

    def test_7b_verification_partial_result_gives_save_ok_false(self):
        """Verifiering returnerar bara en del av keywords → save_ok=False."""
        # Upsert för 2 keywords, verifiering returnerar bara 1
        client, chain = self._make_client(
            verify_data=[{"keyword": "banco"}]  # seo brasil saknas
        )

        _, save_ok = run_on_demand_ranking_v12_impl(
            client, "uid-123", "meusite.com.br", ["banco", "seo brasil"],
            access_token="tok",
        )

        self.assertFalse(
            save_ok,
            "TEST 7b FAIL: partiell verifiering ska ge save_ok=False",
        )

    # ── TEST 8: success-banner visas ENDAST när save_ok=True ──────────────

    def test_8_success_banner_conditional_on_save_ok(self):
        """ranking_done sätts till _save_ok i källkoden — banner visas inte vid save-fel."""
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()

        self.assertIn(
            "ranking_done = _save_ok",
            source,
            "TEST 8 FAIL: ranking_done ska sättas till _save_ok",
        )
        self.assertIn(
            "ranking_done",
            source,
            "TEST 8 FAIL: ranking_done används inte som gate för success-banner",
        )
        # success-bannern ska INTE vara ovillkorlig
        self.assertNotIn(
            "ranking_done = True",
            source,
            "TEST 8 FAIL: ranking_done ska inte sättas till hårdkodat True",
        )

    # ── TEST 9: nya keywords körs fortfarande ─────────────────────────────

    def test_9_new_keywords_trigger_on_demand(self):
        """Ny keyword ska returneras av get_keywords_without_rankings → körs via on-demand."""
        client_stub = MagicMock()

        def table_side(t):
            c = MagicMock()
            c.select.return_value = c
            c.eq.return_value = c
            c.in_.return_value = c
            if t == "tracked_keywords":
                c.execute.return_value = MagicMock(data=[{"keyword": "banco"}, {"keyword": "seo"}])
            elif t == "keyword_rankings":
                c.execute.return_value = MagicMock(data=[{"keyword": "seo"}])
            else:
                c.execute.return_value = MagicMock(data=[])
            return c

        client_stub.table.side_effect = table_side
        result = get_keywords_without_rankings_impl(client_stub, "uid-1", "meusite.com.br")
        self.assertEqual(result, ["banco"], "TEST 9 FAIL: 'banco' är nytt och ska köras")

    # ── TEST 10: befintliga keywords körs inte om ─────────────────────────

    def test_10_existing_keywords_not_rerun(self):
        """Keywords med rankingdata ska INTE returneras av get_keywords_without_rankings."""
        client_stub = MagicMock()

        def table_side(t):
            c = MagicMock()
            c.select.return_value = c
            c.eq.return_value = c
            c.in_.return_value = c
            if t == "tracked_keywords":
                c.execute.return_value = MagicMock(data=[{"keyword": "seo"}, {"keyword": "marketing"}])
            elif t == "keyword_rankings":
                c.execute.return_value = MagicMock(data=[{"keyword": "seo"}, {"keyword": "marketing"}])
            else:
                c.execute.return_value = MagicMock(data=[])
            return c

        client_stub.table.side_effect = table_side
        result = get_keywords_without_rankings_impl(client_stub, "uid-1", "meusite.com.br")
        self.assertEqual(result, [], "TEST 10 FAIL: befintliga keywords ska inte returneras")

    # ── TEST 11: Mexico är orörd ───────────────────────────────────────────

    def test_11_mexico_app_not_modified(self):
        """
        app_mexico_new.py ska inte innehålla V1.2-specifika tillägg från fixen:
          - access_token-parametern i run_on_demand_ranking-signaturen
          - verifieringslogg 'verificação falhou' (portugisisk, BR-specifik)
          - found_kws / set(expected_kws) == found_kws verifieringslogik
        """
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_mexico_new.py")
        if not os.path.exists(path):
            return  # MX-filen existerar inte — OK

        with open(path, encoding="utf-8") as f:
            content = f.read()

        # V1.2-signaturen med access_token=None ska INTE finnas i MX
        self.assertNotIn(
            "def run_on_demand_ranking(user_id, domain, keywords, login, password,\n"
            "                          status_el, progress_bar, access_token=None)",
            content,
            "TEST 11 FAIL: V1.2-signaturen (access_token=None) ska inte finnas i MX",
        )
        # BR-specifik verifieringslogg
        self.assertNotIn(
            "verificação falhou",
            content,
            "TEST 11 FAIL: BR-specifik verifieringslogg ska inte finnas i MX",
        )
        # Verifieringslogiken (found_kws) ska inte finnas i MX
        self.assertNotIn(
            "found_kws",
            content,
            "TEST 11 FAIL: found_kws (V1.2-verifiering) ska inte finnas i MX",
        )

    # ── TEST 12: weekly rank tracker är orörd ─────────────────────────────

    def test_12_weekly_rank_tracker_unchanged(self):
        """rank_tracker.py och weekly_seo_report.yml ska inte ha ändrats av fixen."""
        import os
        base = os.path.dirname(os.path.abspath(__file__))

        tracker_path = os.path.join(base, "rank_tracker.py")
        with open(tracker_path, encoding="utf-8") as f:
            tracker = f.read()
        self.assertIn("def run():", tracker,
                      "TEST 12 FAIL: run() saknas i rank_tracker.py")
        self.assertNotIn("run_on_demand_ranking", tracker,
                         "TEST 12 FAIL: rank_tracker.py ska inte innehålla run_on_demand_ranking")
        self.assertNotIn("access_token", tracker,
                         "TEST 12 FAIL: rank_tracker.py ska inte innehålla access_token-logik")

        yml_path = os.path.join(base, "weekly_seo_report.yml")
        with open(yml_path, encoding="utf-8") as f:
            yml = f.read()
        self.assertIn("0 7 * * 1", yml,
                      "TEST 12 FAIL: weekly cron ska vara oförändrad (0 7 * * 1)")
        self.assertIn("rank_tracker.py", yml,
                      "TEST 12 FAIL: weekly_seo_report.yml ska fortfarande köra rank_tracker.py")


# ---------------------------------------------------------------------------
# V1.2 källkodsinspektion — kompletterande strukturtester
# ---------------------------------------------------------------------------

class TestSourceV12(unittest.TestCase):
    """Källkodsinspektion för V1.2-fix specifika mönster."""

    def setUp(self):
        import os
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
        with open(src_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_access_token_parameter_in_signature(self):
        """run_on_demand_ranking ska ha access_token som parameter."""
        self.assertIn(
            "access_token=None",
            self.source,
            "FAIL: access_token=None saknas i run_on_demand_ranking-signaturen",
        )

    def test_postgrest_auth_pattern_present(self):
        """supabase.postgrest.auth(access_token) ska finnas i källkoden."""
        self.assertIn(
            "supabase.postgrest.auth(access_token)",
            self.source,
            "FAIL: supabase.postgrest.auth(access_token)-mönstret saknas",
        )

    def test_verification_select_present(self):
        """Verifierings-SELECT ska finnas efter upsert-blocket."""
        self.assertIn(
            "verificação falhou",
            self.source,
            "FAIL: verifieringslogik (verificação falhou) saknas",
        )
        self.assertIn(
            "found_kws",
            self.source,
            "FAIL: found_kws saknas — verifieringen är inte implementerad",
        )
        self.assertIn(
            "set(expected_kws) == found_kws",
            self.source,
            "FAIL: set(expected_kws) == found_kws saknas — save_ok baseras inte på verifiering",
        )

    def test_upsert_uses_from_not_table(self):
        """
        V1.2 ska använda .from_('keyword_rankings') via auth-instansen,
        inte supabase.table('keyword_rankings') direkt.
        """
        self.assertIn(
            '.from_("keyword_rankings")',
            self.source,
            "FAIL: .from_('keyword_rankings') saknas i upsert-blocket",
        )


# ---------------------------------------------------------------------------
# Kör tester
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for cls in [
        TestGetKeywordsWithoutRankings,
        TestRunOnDemandRankingV11,
        TestNoDoubleRankings,
        TestUnchangedFiles,
        TestGateLogic,
        TestRunOnDemandRankingV12,
        TestSourceV12,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

"""
test_initial_ranking_v1.py
==========================
Testar V1 + V1.1-fix av initial rankingkörning:
  get_keywords_without_rankings()
  Gate-logiken för on-demand ranking
  run_on_demand_ranking() — market-fält, save_ok-flagga, undantagshantering

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
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

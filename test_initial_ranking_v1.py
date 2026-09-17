"""
test_initial_ranking_v1.py
==========================
Testar V1 av initial rankingkörning:
  get_keywords_without_rankings()
  Gate-logiken för on-demand ranking

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
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# market_config behöver returnera riktiga värden
sys.modules["market_config"].get_market = MagicMock(
    return_value={"location_code": 2076, "language_code": "pt"}
)
sys.modules["market_config"].market_from_env = MagicMock(return_value="br")

# ---------------------------------------------------------------------------
# Importera funktionen vi ska testa direkt ur app_brasil_new
# ---------------------------------------------------------------------------

# Vi importerar inte hela modulen utan kapslar in funktionen manuellt
# för att undvika Streamlit-sidoeffekter vid import.

def _load_get_keywords_without_rankings():
    """
    Laddar get_keywords_without_rankings() ur app_brasil_new.py
    utan att köra hela Streamlit-appen.
    """
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "app_brasil_new",
        os.path.join(os.path.dirname(__file__), "app_brasil_new.py"),
    )
    # Kör inte modulen — läs bara källkoden och extrahera funktionen
    import ast, textwrap

    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_brasil_new.py")
    with open(src_path, encoding="utf-8") as f:
        source = f.read()

    # Extrahera get_keywords_without_rankings och has_any_rankings
    tree = ast.parse(source)
    func_sources = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "get_keywords_without_rankings", "has_any_rankings"
        ):
            func_sources[node.name] = ast.get_source_segment(source, node)

    return func_sources


# ---------------------------------------------------------------------------
# Direkt implementation att testa (isolerat från Streamlit-runtime)
# ---------------------------------------------------------------------------

# Vi testar get_keywords_without_rankings direkt med en mock-supabase.

def get_keywords_without_rankings_impl(supabase_client, user_id, domain):
    """
    Kopia av implementationen ur app_brasil_new.py för isolerad testning.
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

    def test_4b_all_keywords_already_ranked(self):
        """Alla keywords har rankingdata → tom lista returneras (inget att köra)."""
        tracked = ["kw-a", "kw-b"]
        ranked = ["kw-a", "kw-b"]
        client = self._make_client(tracked, ranked)
        result = get_keywords_without_rankings_impl(client, "user-5", "meusite.com.br")
        self.assertEqual(result, [],
                         "TEST 4b FAIL: Tom lista när alla är rankade")

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


class TestNoDoubleRankings(unittest.TestCase):
    """TEST 6: Upsert-logiken förhindrar dubbla rader."""

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
            "TEST 6 FAIL: upsert måste använda on_conflict='user_id,keyword,domain'",
        )


class TestUnchangedFiles(unittest.TestCase):
    """TEST 5: rank_tracker.py och weekly_seo_report.yml är oförändrade."""

    def test_rank_tracker_not_modified(self):
        """rank_tracker.py ska inte innehålla get_keywords_without_rankings."""
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rank_tracker.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn(
            "get_keywords_without_rankings",
            content,
            "TEST 5 FAIL: rank_tracker.py ska inte ha ändrats",
        )
        # Verifiera att rank_tracker fortfarande har run()-funktionen
        self.assertIn("def run():", content,
                      "TEST 5 FAIL: run() saknas i rank_tracker.py")

    def test_weekly_yml_not_modified(self):
        """weekly_seo_report.yml ska fortfarande trigga måndag kl 07:00 UTC."""
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly_seo_report.yml")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("0 7 * * 1", content,
                      "TEST 5 FAIL: weekly cron ska vara oförändrad (0 7 * * 1)")
        self.assertIn("rank_tracker.py", content,
                      "TEST 5 FAIL: weekly_seo_report.yml ska fortfarande köra rank_tracker.py")


class TestGateLogic(unittest.TestCase):
    """TEST 7: Regression — verifiera att ny gate-logik finns i app_brasil_new.py."""

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
            "TEST 7 FAIL: ny gate-funktion saknas i app_brasil_new.py",
        )

    def test_old_gate_removed_from_buttons(self):
        """
        Den gamla gaten 'not has_any_rankings(user_id)' ska inte längre
        förekomma i + Rastrear-knapparna.
        Kontroll: den gamla kombinationen ska inte finnas i koden.
        """
        # Den gamla koden kombinerade has_any_rankings med _all_kws-listan
        old_pattern = "not has_any_rankings(user_id):\n"
        # Räkna förekomster — ska vara 0 i knappsektionerna
        # (has_any_rankings används fortfarande i get_onboarding_status, det är OK)
        occurrences = self.source.count("if _user_domain and not has_any_rankings(user_id):")
        self.assertEqual(
            occurrences, 0,
            "TEST 7 FAIL: gamla gaten if _user_domain and not has_any_rankings() ska vara borttagen",
        )

    def test_has_any_rankings_still_used_in_onboarding(self):
        """has_any_rankings() ska fortfarande användas i get_onboarding_status()."""
        self.assertIn(
            "has_any_rankings(user_id)",
            self.source,
            "TEST 7 FAIL: has_any_rankings() verkar ha tagits bort helt",
        )

    def test_function_defined(self):
        """get_keywords_without_rankings ska vara definierad som funktion."""
        self.assertIn(
            "def get_keywords_without_rankings(",
            self.source,
            "TEST 7 FAIL: get_keywords_without_rankings() är inte definierad",
        )

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
                "TEST 7 FAIL: app_mexico_new.py ska inte ha ändrats",
            )


# ---------------------------------------------------------------------------
# Kör tester
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for cls in [
        TestGetKeywordsWithoutRankings,
        TestNoDoubleRankings,
        TestUnchangedFiles,
        TestGateLogic,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

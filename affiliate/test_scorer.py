"""
affiliate/test_scorer.py
========================
Tests for scorer.py — verifies that:
  1. _build_product_test_criteria_text() exists and returns the expected content.
  2. build_prompt() JSON schema includes all 4 new product_test fields.
  3. score_model.py is untouched (version locked at v1.2, 8 categories, 100 points).
  4. product_test_potential is isolated from affiliate score:
       - total_score is recalculated from categories only (new fields not included).
       - grade is derived from total_score only.
  5. score_candidate() fallback validation works when model returns invalid PTP level.

Run with:
    python affiliate/test_scorer.py
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make sure affiliate/ is importable when run from repo root
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Import modules under test
# ---------------------------------------------------------------------------

from score_model import SCORE_MODEL, get_classification
import scorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_candidate() -> dict:
    return {
        "name": "Teste Candidato",
        "type": "consultant",
        "platform": "LinkedIn",
        "url": "https://exemplo.com.br",
        "company": "SEO Ltda",
        "description": "Consultor SEO com foco em clientes brasileiros.",
        "audience": "Agências e empresas que precisam de SEO",
        "content": "Artigos sobre SEO no LinkedIn",
        "affiliate_experience": "Hotmart",
        "brazil_presence": "São Paulo, SP",
    }


def _make_api_response(extra_fields: dict | None = None) -> dict:
    """Return a minimal valid scorer result matching the JSON schema."""
    base = {
        "candidate_name": "Teste Candidato",
        "knocked_out": False,
        "knockout_reason": None,
        "categories": {
            "target_audience_fit": {"score": 25, "max": 30, "insufficient_evidence": False, "evidence": "ok"},
            "seo_relevance": {"score": 16, "max": 20, "insufficient_evidence": False, "evidence": "ok"},
            "purchase_influence": {"score": 12, "max": 15, "insufficient_evidence": False, "evidence": "ok"},
            "reach_quality": {"score": 7, "max": 10, "insufficient_evidence": False, "evidence": "ok"},
            "customer_volume_potential": {"score": 7, "max": 10, "insufficient_evidence": False, "evidence": "ok"},
            "brazil_fit": {"score": 4, "max": 5, "insufficient_evidence": False, "evidence": "ok"},
            "affiliate_fit": {"score": 4, "max": 5, "insufficient_evidence": False, "evidence": "ok"},
            "content_traffic_potential": {"score": 4, "max": 5, "insufficient_evidence": False, "evidence": "ok"},
        },
        "total_score": 79,  # Intentionally wrong — scorer recalculates
        "grade": "C",       # Intentionally wrong — scorer recalculates
        "grade_label": "wrong",
        "why_interesting": "Interessante.",
        "outreach_angle": "Olá, temos uma proposta.",
        "product_test_potential": "HIGH",
        "product_test_evidence": "É consultor SEO com presença no LinkedIn.",
        "product_test_reason": "SEO-fokus och aktiv innehållsproduktion.",
        "recommended_action": "Skicka testlicens inom 48h.",
    }
    if extra_fields:
        base.update(extra_fields)
    return base


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestScoreModelIntegrity(unittest.TestCase):
    """score_model.py must remain locked at v1.2."""

    def test_version_is_1_2(self):
        self.assertEqual(SCORE_MODEL["version"], "1.2",
                         "score_model.py version must stay at 1.2 — do not modify it.")

    def test_total_points_100(self):
        self.assertEqual(SCORE_MODEL["total_points"], 100,
                         "Total points must be 100.")

    def test_exactly_8_categories(self):
        self.assertEqual(len(SCORE_MODEL["categories"]), 8,
                         "Must have exactly 8 scoring categories.")

    def test_category_max_sums_to_100(self):
        total = sum(c["max_points"] for c in SCORE_MODEL["categories"])
        self.assertEqual(total, 100,
                         f"Category max_points must sum to 100, got {total}.")

    def test_has_4_knockout_filters(self):
        self.assertEqual(len(SCORE_MODEL["knockout_filters"]), 4,
                         "Must have exactly 4 knockout filters.")

    def test_classification_unchanged(self):
        # A+ = 90–100, A = 80–89, B = 70–79, C = 60–69, Skip = 0–59
        grades = [(c["min"], c["max"], c["grade"]) for c in SCORE_MODEL["classification"]]
        expected = [(90, 100, "A+"), (80, 89, "A"), (70, 79, "B"), (60, 69, "C"), (0, 59, "Skip")]
        self.assertEqual(grades, expected)


class TestProductTestCriteriaText(unittest.TestCase):
    """_build_product_test_criteria_text() must exist and contain required content."""

    def test_function_exists(self):
        self.assertTrue(hasattr(scorer, "_build_product_test_criteria_text"),
                        "scorer._build_product_test_criteria_text must exist.")

    def test_returns_string(self):
        text = scorer._build_product_test_criteria_text()
        self.assertIsInstance(text, str)

    def test_contains_all_four_levels(self):
        text = scorer._build_product_test_criteria_text()
        for level in ["VERY HIGH", "HIGH", "MEDIUM", "LOW"]:
            self.assertIn(level, text, f"Level '{level}' must be in criteria text.")

    def test_contains_independence_notice(self):
        text = scorer._build_product_test_criteria_text()
        self.assertIn("INTE Affiliate Score", text,
                      "Criteria text must state independence from Affiliate Score.")

    def test_contains_evidence_over_assumption_rule(self):
        text = scorer._build_product_test_criteria_text()
        self.assertIn("spekulera", text.lower(),
                      "Criteria text must warn against speculation.")


class TestBuildPromptSchema(unittest.TestCase):
    """build_prompt() must include all 4 new product_test fields in JSON schema."""

    def setUp(self):
        self.prompt = scorer.build_prompt(_fake_candidate())

    def test_contains_product_test_potential_field(self):
        self.assertIn('"product_test_potential"', self.prompt)

    def test_contains_product_test_evidence_field(self):
        self.assertIn('"product_test_evidence"', self.prompt)

    def test_contains_product_test_reason_field(self):
        self.assertIn('"product_test_reason"', self.prompt)

    def test_contains_recommended_action_field(self):
        self.assertIn('"recommended_action"', self.prompt)

    def test_contains_ptp_levels_in_prompt(self):
        for level in ["VERY HIGH", "HIGH", "MEDIUM", "LOW"]:
            self.assertIn(level, self.prompt)

    def test_contains_independence_instruction(self):
        self.assertIn("OBEROENDE", self.prompt,
                      "Prompt must tell model that PTP is independent of affiliate score.")

    def test_contains_existing_affiliate_score_criteria(self):
        """Affiliate Score v1.2 criteria must still be present in the prompt."""
        self.assertIn("AFFILIATE SCORE", self.prompt)
        self.assertIn("KNOCKOUT", self.prompt)

    def test_prompt_is_a_string(self):
        self.assertIsInstance(self.prompt, str)


class TestScoreCandidateIsolation(unittest.TestCase):
    """product_test_potential must NOT affect total_score or grade."""

    def _run_score_with_mock(self, response_override: dict | None = None) -> dict:
        """Patch the Anthropic client and return score_candidate() output."""
        api_response = _make_api_response(response_override)
        raw_json = json.dumps(api_response)

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=raw_json)]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-not-real"}):
            with patch("anthropic.Anthropic", return_value=mock_client):
                return scorer.score_candidate(_fake_candidate())

    def test_total_score_recalculated_from_categories(self):
        result = self._run_score_with_mock()
        # Categories sum: 25+16+12+7+7+4+4+4 = 79
        self.assertEqual(result["total_score"], 79)

    def test_grade_derived_from_total_score(self):
        result = self._run_score_with_mock()
        # 79 → B
        self.assertEqual(result["grade"], "B")

    def test_ptp_does_not_affect_total_score(self):
        """Change PTP to VERY HIGH — total_score must remain the same."""
        result_high = self._run_score_with_mock({"product_test_potential": "VERY HIGH"})
        result_low = self._run_score_with_mock({"product_test_potential": "LOW"})
        self.assertEqual(result_high["total_score"], result_low["total_score"],
                         "total_score must be identical regardless of product_test_potential.")

    def test_ptp_does_not_affect_grade(self):
        result_high = self._run_score_with_mock({"product_test_potential": "VERY HIGH"})
        result_low = self._run_score_with_mock({"product_test_potential": "LOW"})
        self.assertEqual(result_high["grade"], result_low["grade"],
                         "grade must be identical regardless of product_test_potential.")

    def test_ptp_field_present_in_result(self):
        result = self._run_score_with_mock()
        self.assertIn("product_test_potential", result)

    def test_all_4_new_fields_present(self):
        result = self._run_score_with_mock()
        for field in ["product_test_potential", "product_test_evidence",
                      "product_test_reason", "recommended_action"]:
            self.assertIn(field, result, f"Field '{field}' must be present in result.")

    def test_ptp_value_is_valid_level(self):
        result = self._run_score_with_mock()
        self.assertIn(result["product_test_potential"], {"VERY HIGH", "HIGH", "MEDIUM", "LOW"})


class TestScoreCandidateFallback(unittest.TestCase):
    """score_candidate() must fall back gracefully when model returns invalid PTP."""

    def _run_with_invalid_ptp(self, ptp_value) -> dict:
        api_response = _make_api_response({"product_test_potential": ptp_value})
        raw_json = json.dumps(api_response)

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=raw_json)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-not-real"}):
            with patch("anthropic.Anthropic", return_value=mock_client):
                return scorer.score_candidate(_fake_candidate())

    def test_invalid_ptp_falls_back_to_low(self):
        result = self._run_with_invalid_ptp("UNKNOWN_LEVEL")
        self.assertEqual(result["product_test_potential"], "LOW")

    def test_empty_ptp_falls_back_to_low(self):
        result = self._run_with_invalid_ptp("")
        self.assertEqual(result["product_test_potential"], "LOW")

    def test_none_ptp_falls_back_to_low(self):
        result = self._run_with_invalid_ptp(None)
        self.assertEqual(result["product_test_potential"], "LOW")

    def test_fallback_does_not_affect_total_score(self):
        result = self._run_with_invalid_ptp("GARBAGE")
        self.assertEqual(result["total_score"], 79)
        self.assertEqual(result["grade"], "B")


class TestFormatReport(unittest.TestCase):
    """format_report() must include the product test section."""

    def _make_result(self) -> dict:
        r = _make_api_response()
        r["total_score"] = 79
        r["grade"] = "B"
        r["grade_label"] = "Bom candidato"
        return r

    def test_product_test_section_header_present(self):
        report = scorer.format_report(_fake_candidate(), self._make_result())
        self.assertIn("Product Test Potential", report)

    def test_ptp_level_in_report(self):
        report = scorer.format_report(_fake_candidate(), self._make_result())
        self.assertIn("HIGH", report)

    def test_evidence_in_report(self):
        result = self._make_result()
        report = scorer.format_report(_fake_candidate(), result)
        self.assertIn(result["product_test_evidence"], report)

    def test_recommended_action_in_report(self):
        result = self._make_result()
        report = scorer.format_report(_fake_candidate(), result)
        self.assertIn(result["recommended_action"], report)

    def test_independence_notice_in_report(self):
        report = scorer.format_report(_fake_candidate(), self._make_result())
        self.assertIn("Oberoende signal", report)

    def test_affiliate_score_section_still_present(self):
        """Affiliate Score v1.2 sections must not be removed."""
        report = scorer.format_report(_fake_candidate(), self._make_result())
        self.assertIn("Total Score:", report)
        self.assertIn("Scoring per kategori", report)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestScoreModelIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestProductTestCriteriaText))
    suite.addTests(loader.loadTestsFromTestCase(TestBuildPromptSchema))
    suite.addTests(loader.loadTestsFromTestCase(TestScoreCandidateIsolation))
    suite.addTests(loader.loadTestsFromTestCase(TestScoreCandidateFallback))
    suite.addTests(loader.loadTestsFromTestCase(TestFormatReport))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

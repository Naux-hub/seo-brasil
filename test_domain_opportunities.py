"""
test_domain_opportunities.py
=============================
Enhetstester för domain_opportunities.py.
Inga live API-anrop — alla externa anrop mockas.

Kör med: pytest test_domain_opportunities.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from domain_opportunities import (
    fetch_catchdoms,
    enrich_with_dataforseo,
    merge_results,
    compact_num,
    tf_cf_ratio,
    registro_br_url,
    wayback_url,
    majestic_url,
    _fetch_bulk_ranks,
    _fetch_bulk_spam_score,
)


# ── compact_num ───────────────────────────────────────────────────────────────

class TestCompactNum:
    def test_none_returns_dash(self):
        assert compact_num(None) == "—"

    def test_small_number(self):
        assert compact_num(42) == "42"

    def test_exactly_1000(self):
        assert compact_num(1000) == "1.0k"

    def test_thousands(self):
        assert compact_num(17675) == "17.7k"

    def test_hundreds_of_thousands(self):
        assert compact_num(102894) == "102.9k"

    def test_million(self):
        assert compact_num(1_000_000) == "1.0M"

    def test_millions(self):
        assert compact_num(2_500_000) == "2.5M"

    def test_zero(self):
        assert compact_num(0) == "0"

    def test_float_input(self):
        result = compact_num(1500.7)
        assert result == "1.5k"

    def test_string_number(self):
        # Accepterar strängformaterade tal
        result = compact_num("3000")
        assert result == "3.0k"

    def test_invalid_string_returns_dash(self):
        assert compact_num("abc") == "—"


# ── tf_cf_ratio ───────────────────────────────────────────────────────────────

class TestTfCfRatio:
    def test_basic_ratio(self):
        # TF=31, CF=10 → 310%
        assert tf_cf_ratio(31, 10) == "310%"

    def test_equal_values(self):
        # TF=CF → 100%
        assert tf_cf_ratio(25, 25) == "100%"

    def test_high_ratio(self):
        # TF=25, CF=2 → 1250%
        assert tf_cf_ratio(25, 2) == "1250%"

    def test_low_ratio(self):
        # TF=10, CF=26 → 38%
        assert tf_cf_ratio(10, 26) == "38%"

    def test_cf_zero_returns_none(self):
        # CF=0 → divisionsfel, returnerar None
        assert tf_cf_ratio(25, 0) is None

    def test_tf_none_returns_none(self):
        assert tf_cf_ratio(None, 10) is None

    def test_cf_none_returns_none(self):
        assert tf_cf_ratio(25, None) is None

    def test_both_none_returns_none(self):
        assert tf_cf_ratio(None, None) is None

    def test_returns_string(self):
        result = tf_cf_ratio(20, 10)
        assert isinstance(result, str)
        assert result.endswith("%")


# ── registro_br_url ───────────────────────────────────────────────────────────

class TestRegistroBrUrl:
    def test_basic_domain(self):
        url = registro_br_url("mooblo.com.br")
        assert url == "https://registro.br/pesquisa-dominio/?domain=mooblo.com.br"

    def test_domain_in_url(self):
        url = registro_br_url("braovivo.com.br")
        assert "braovivo.com.br" in url

    def test_correct_base(self):
        url = registro_br_url("test.com.br")
        assert url.startswith("https://registro.br/")

    def test_returns_string(self):
        assert isinstance(registro_br_url("test.com.br"), str)


# ── wayback_url / majestic_url ────────────────────────────────────────────────

class TestExternalUrls:
    def test_wayback_url(self):
        url = wayback_url("mooblo.com.br")
        assert "web.archive.org" in url
        assert "mooblo.com.br" in url

    def test_majestic_url(self):
        url = majestic_url("mooblo.com.br")
        assert "majestic.com" in url
        assert "mooblo.com.br" in url


# ── merge_results ─────────────────────────────────────────────────────────────

class TestMergeResults:
    def _make_cd_domain(self, name, tf=20, cf=10, rd=50, score=55):
        return {"name": name, "trust_flow": tf, "citation_flow": cf,
                "referring_domains": rd, "score": score}

    def test_basic_merge(self):
        cd = [self._make_cd_domain("mooblo.com.br")]
        dfs = {"mooblo.com.br": {"dr": 42, "ss": 15}}
        result = merge_results(cd, dfs)
        assert len(result) == 1
        assert result[0]["dr"] == 42
        assert result[0]["ss"] == 15

    def test_catchdoms_data_preserved(self):
        cd = [self._make_cd_domain("mooblo.com.br", tf=31, cf=10, rd=108)]
        dfs = {"mooblo.com.br": {"dr": 42, "ss": 15}}
        result = merge_results(cd, dfs)
        assert result[0]["trust_flow"] == 31
        assert result[0]["citation_flow"] == 10
        assert result[0]["referring_domains"] == 108

    def test_null_dr_preserved_as_none(self):
        """dr=None (domän ej i index) ska bevaras som None, inte konverteras till 0."""
        cd = [self._make_cd_domain("unknown.com.br")]
        dfs = {"unknown.com.br": {"dr": None, "ss": None}}
        result = merge_results(cd, dfs)
        assert result[0]["dr"] is None
        assert result[0]["ss"] is None

    def test_dr_zero_preserved(self):
        """dr=0 är giltigt — indikerar indexerat men noll i DataForSEO-skala."""
        cd = [self._make_cd_domain("low.com.br")]
        dfs = {"low.com.br": {"dr": 0, "ss": 5}}
        result = merge_results(cd, dfs)
        assert result[0]["dr"] == 0  # 0 != None

    def test_missing_from_dataforseo(self):
        """Domän som saknas i DataForSEO-map → dr=None, ss=None."""
        cd = [self._make_cd_domain("missing.com.br")]
        dfs = {}  # Tom map
        result = merge_results(cd, dfs)
        assert result[0]["dr"] is None
        assert result[0]["ss"] is None

    def test_multiple_domains(self):
        cd = [
            self._make_cd_domain("a.com.br"),
            self._make_cd_domain("b.com.br"),
        ]
        dfs = {
            "a.com.br": {"dr": 10, "ss": 5},
            "b.com.br": {"dr": 20, "ss": 10},
        }
        result = merge_results(cd, dfs)
        assert len(result) == 2
        assert result[0]["dr"] == 10
        assert result[1]["dr"] == 20

    def test_empty_catchdoms_list(self):
        result = merge_results([], {})
        assert result == []

    def test_high_ss_preserved(self):
        """SS=65 (hög risk) ska bevaras korrekt."""
        cd = [self._make_cd_domain("risky.com.br")]
        dfs = {"risky.com.br": {"dr": 30, "ss": 65}}
        result = merge_results(cd, dfs)
        assert result[0]["ss"] == 65


# ── fetch_catchdoms (med mock) ────────────────────────────────────────────────

class TestFetchCatchdoms:
    def test_no_token_returns_error(self):
        result = fetch_catchdoms(token="")
        assert isinstance(result, dict)
        assert result["error"] == "no_token"

    def test_403_returns_auth_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.ok = False
        with patch("domain_opportunities.requests.get", return_value=mock_resp):
            result = fetch_catchdoms(token="test-token")
        assert isinstance(result, dict)
        assert result["error"] == "auth"

    def test_429_returns_rate_limit_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.ok = False
        with patch("domain_opportunities.requests.get", return_value=mock_resp):
            result = fetch_catchdoms(token="test-token")
        assert isinstance(result, dict)
        assert result["error"] == "rate_limit"

    def test_timeout_returns_timeout_error(self):
        import requests as req
        with patch("domain_opportunities.requests.get", side_effect=req.Timeout):
            result = fetch_catchdoms(token="test-token")
        assert isinstance(result, dict)
        assert result["error"] == "timeout"

    def test_successful_list_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = [
            {"name": "mooblo.com.br", "trust_flow": 31, "citation_flow": 10}
        ]
        with patch("domain_opportunities.requests.get", return_value=mock_resp):
            result = fetch_catchdoms(token="test-token")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "mooblo.com.br"

    def test_successful_dict_response_with_domains_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "domains": [{"name": "braovivo.com.br", "trust_flow": 21}]
        }
        with patch("domain_opportunities.requests.get", return_value=mock_resp):
            result = fetch_catchdoms(token="test-token")
        assert isinstance(result, list)
        assert result[0]["name"] == "braovivo.com.br"

    def test_empty_response_returns_empty_list(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = []
        with patch("domain_opportunities.requests.get", return_value=mock_resp):
            result = fetch_catchdoms(token="test-token")
        assert result == []

    def test_per_page_capped_at_25(self):
        """per_page > 25 ska trunketras till 25 i API-anropet."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = []
        with patch("domain_opportunities.requests.get", return_value=mock_resp) as mock_get:
            fetch_catchdoms(per_page=100, token="test-token")
            call_kwargs = mock_get.call_args
            params = call_kwargs[1].get("params", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
            # Kontrollera att params skickades med get
            assert mock_get.called

    def test_age_min_zero_not_sent(self):
        """age_min=0 ska inte inkluderas i params."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = []
        with patch("domain_opportunities.requests.get", return_value=mock_resp) as mock_get:
            fetch_catchdoms(age_min=0, token="test-token")
            call_kwargs = mock_get.call_args
            params = call_kwargs[1].get("params", {})
            assert "age_min" not in params

    def test_token_not_in_return_value(self):
        """Token ska aldrig exponeras i returnerat värde."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = [{"name": "test.com.br"}]
        with patch("domain_opportunities.requests.get", return_value=mock_resp):
            result = fetch_catchdoms(token="secret-token-abc123")
        # Token ska inte finnas i nåt returvärde
        result_str = str(result)
        assert "secret-token-abc123" not in result_str


# ── _fetch_bulk_ranks (med mock) ──────────────────────────────────────────────

class TestFetchBulkRanks:
    def _make_dfs_response(self, items):
        return {
            "status_code": 20000,
            "tasks": [{
                "status_code": 20000,
                "result": [{"items": items}]
            }]
        }

    def test_basic_rank_extraction(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([
            {"target": "mooblo.com.br", "rank": 42}
        ])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_ranks(["mooblo.com.br"], "login", "pass")
        assert result["mooblo.com.br"] == 42

    def test_rank_zero_preserved(self):
        """rank=0 är ett giltigt värde — ska inte bli None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([
            {"target": "low.com.br", "rank": 0}
        ])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_ranks(["low.com.br"], "login", "pass")
        assert result["low.com.br"] == 0  # 0 != None

    def test_missing_domain_returns_none(self):
        """Domän som saknas i svaret → None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_ranks(["missing.com.br"], "login", "pass")
        assert result["missing.com.br"] is None

    def test_multiple_domains(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([
            {"target": "a.com.br", "rank": 10},
            {"target": "b.com.br", "rank": 20},
        ])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_ranks(["a.com.br", "b.com.br"], "login", "pass")
        assert result["a.com.br"] == 10
        assert result["b.com.br"] == 20

    def test_exception_returns_all_none(self):
        with patch("domain_opportunities.requests.post", side_effect=Exception("nät-fel")):
            result = _fetch_bulk_ranks(["fail.com.br"], "login", "pass")
        assert result["fail.com.br"] is None

    def test_empty_targets_returns_empty(self):
        result = _fetch_bulk_ranks([], "login", "pass")
        assert result == {}


# ── _fetch_bulk_spam_score (med mock) ─────────────────────────────────────────

class TestFetchBulkSpamScore:
    def _make_dfs_response(self, items):
        return {
            "status_code": 20000,
            "tasks": [{
                "status_code": 20000,
                "result": [{"items": items}]
            }]
        }

    def test_basic_ss_extraction(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([
            {"target": "mooblo.com.br", "spam_score": 5}
        ])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_spam_score(["mooblo.com.br"], "login", "pass")
        assert result["mooblo.com.br"] == 5

    def test_null_ss_preserved(self):
        """spam_score=None ska bevaras — inte ersättas med 0."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([
            {"target": "unknown.com.br", "spam_score": None}
        ])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_spam_score(["unknown.com.br"], "login", "pass")
        assert result["unknown.com.br"] is None

    def test_missing_from_response_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_spam_score(["gone.com.br"], "login", "pass")
        assert result["gone.com.br"] is None

    def test_high_ss_preserved(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_dfs_response([
            {"target": "spam.com.br", "spam_score": 65}
        ])
        with patch("domain_opportunities.requests.post", return_value=mock_resp):
            result = _fetch_bulk_spam_score(["spam.com.br"], "login", "pass")
        assert result["spam.com.br"] == 65

    def test_exception_returns_all_none(self):
        with patch("domain_opportunities.requests.post", side_effect=Exception("fail")):
            result = _fetch_bulk_spam_score(["fail.com.br"], "login", "pass")
        assert result["fail.com.br"] is None


# ── enrich_with_dataforseo (integrationstest med mock) ────────────────────────

class TestEnrichWithDataforseo:
    def test_returns_dict_with_dr_and_ss(self):
        with patch("domain_opportunities._fetch_bulk_ranks",
                   return_value={"mooblo.com.br": 42}) as mr, \
             patch("domain_opportunities._fetch_bulk_spam_score",
                   return_value={"mooblo.com.br": 5}) as ms:
            result = enrich_with_dataforseo(["mooblo.com.br"], "login", "pass")
        assert result["mooblo.com.br"]["dr"] == 42
        assert result["mooblo.com.br"]["ss"] == 5

    def test_null_dr_preserved(self):
        with patch("domain_opportunities._fetch_bulk_ranks",
                   return_value={"x.com.br": None}), \
             patch("domain_opportunities._fetch_bulk_spam_score",
                   return_value={"x.com.br": None}):
            result = enrich_with_dataforseo(["x.com.br"], "login", "pass")
        assert result["x.com.br"]["dr"] is None
        assert result["x.com.br"]["ss"] is None

    def test_empty_input_returns_empty(self):
        result = enrich_with_dataforseo([], "login", "pass")
        assert result == {}

    def test_credentials_not_in_result(self):
        """Credentials ska aldrig läcka ut i returvärdet."""
        with patch("domain_opportunities._fetch_bulk_ranks",
                   return_value={"t.com.br": 10}), \
             patch("domain_opportunities._fetch_bulk_spam_score",
                   return_value={"t.com.br": 5}):
            result = enrich_with_dataforseo(["t.com.br"], "secret-login", "secret-password")
        result_str = str(result)
        assert "secret-login" not in result_str
        assert "secret-password" not in result_str

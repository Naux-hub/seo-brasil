"""
market_config.py
================
Centralized market configuration for SEO Brasil / SEO México.

Usage:
    from market_config import get_market, MARKETS

    cfg = get_market("br")   # or get_market("mx")
    location_code  = cfg["location_code"]    # e.g. 2076
    language_code  = cfg["language_code"]    # e.g. "pt"

This module is intentionally import-only — no side effects, no I/O.
Both rank_tracker.py and keyword_cache.py read MARKET from their
environment (defaulting to "br") and call get_market() once at startup.

DO NOT add market-routing logic to app_brasil_new.py — that file is
the production Brazil entry point and must remain unchanged.
"""

from __future__ import annotations
import os

# ---------------------------------------------------------------------------
# Market registry
# ---------------------------------------------------------------------------

MARKETS: dict[str, dict] = {
    "br": {
        # DataForSEO identifiers
        "location_code": 2076,
        "language_code": "pt",
        # Product details
        "product_name": "SEO Brasil",
        "product_url": "https://seobrasil.app",
        "currency": "BRL",
        "price_monthly": "R$197",
        "hotmart_url": "https://pay.hotmart.com/L106736067M",
        # Locale
        "locale": "pt-BR",
        "country": "Brasil",
        # Status
        "status": "active",
    },
    "mx": {
        # DataForSEO identifiers
        "location_code": 2484,
        "language_code": "es",
        # Product details
        "product_name": "SEO México",
        "product_url": "https://seomexico.app",
        "currency": "MXN",
        "price_monthly": None,          # TBD at launch
        "hotmart_url": None,            # TBD at launch
        # Locale
        "locale": "es-MX",
        "country": "México",
        # Status
        "status": "planned",
    },
}

DEFAULT_MARKET = "br"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_market(market_id: str) -> dict:
    """
    Return config dict for *market_id*.

    Raises KeyError for unknown markets so callers fail loudly rather
    than silently using wrong location codes.
    """
    key = market_id.lower().strip()
    if key not in MARKETS:
        raise KeyError(
            f"Unknown market '{market_id}'. Available: {list(MARKETS.keys())}"
        )
    return MARKETS[key]


def market_from_env(env_var: str = "MARKET", default: str = DEFAULT_MARKET) -> str:
    """
    Read a market ID from an environment variable.

    Returns the validated market ID (lowercase).
    Falls back to *default* if the variable is unset.
    Raises KeyError if the variable is set to an unknown market.
    """
    raw = os.environ.get(env_var, default)
    key = raw.lower().strip()
    if key not in MARKETS:
        raise KeyError(
            f"Environment variable {env_var}='{raw}' is not a recognised market. "
            f"Available: {list(MARKETS.keys())}"
        )
    return key

"""
affiliate/markets.py
====================
Market configuration for the affiliate prospecting engine.

Each market entry provides context that may optionally be used by scorer.py
to adapt prompts for a specific geographic/linguistic market.

STATUS:
  BR — Active (SEO Brasil, seobrasil.app)
  MX — Planned (not yet implemented)

DO NOT add market logic to score_model.py.
The scoring model (v1.2) is market-agnostic and must remain locked.
Market context belongs here, not in the scorer or the model.
"""

from __future__ import annotations

MARKETS: dict[str, dict] = {
    "br": {
        "name": "Brasil",
        "language": "pt-BR",
        "product_name": "SEO Brasil",
        "product_url": "https://seobrasil.app",
        "currency": "BRL",
        "price_monthly": "R$197",
        "affiliate_commission": "30% recurring",
        "affiliate_platform": "Hotmart",
        "prospects_dir": "prospects/br",
        "reports_dir": "reports/br",
        "status": "active",
    },
    "mx": {
        "name": "México",
        "language": "es-MX",
        "product_name": "SEO México",          # placeholder — update when product launches
        "product_url": None,                    # not yet live
        "currency": "MXN",
        "price_monthly": None,                  # TBD
        "affiliate_commission": None,           # TBD
        "affiliate_platform": None,             # TBD
        "prospects_dir": "prospects/mx",
        "reports_dir": "reports/mx",
        "status": "planned",
    },
}

DEFAULT_MARKET = "br"


def get_market(market_id: str) -> dict:
    """Return config for a given market ID. Raises KeyError if unknown."""
    market_id = market_id.lower().strip()
    if market_id not in MARKETS:
        raise KeyError(
            f"Unknown market '{market_id}'. Available: {list(MARKETS.keys())}"
        )
    return MARKETS[market_id]

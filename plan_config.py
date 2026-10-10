"""
plan_config.py
==============
En enda plats för vad varje plan innehåller.

Planer (värdet i subscribers.plan):
  gratis  — R$0    1 domän,  10 sökord, top 30,  4 veckors historik
  basico  — R$39   1 domän,  50 sökord, top 30,  4 veckors historik
  pro     — R$97   3 domäner, 200 sökord, top 100, 12 veckors historik
  premium — R$197  5 domäner, 500 sökord, top 100, 12 veckors historik, Domain Opportunities

Regel: bara subscription_status == "active" ger en betald plan.
Allt annat (trial, cancelled, refunded, chargeback, saknas) räknas som gratis.
Så faller en uppsagd kund automatiskt tillbaka till gratis, utan databasändring.

Länkar till Hotmart läses från miljövariabler (sätts i Railway):
  HOTMART_CHECKOUT_BASICO, HOTMART_CHECKOUT_PRO, HOTMART_CHECKOUT_PREMIUM
Saknas en variabel används produktens standardlänk.
"""

import os

PLANS = {
    "gratis": {
        "label": "Grátis", "price": 0,
        "max_domains": 1, "max_keywords": 10,
        "serp_depth": 30, "history_weeks": 4, "domain_opps": False,
    },
    "basico": {
        "label": "Básico", "price": 39,
        "max_domains": 1, "max_keywords": 50,
        "serp_depth": 30, "history_weeks": 4, "domain_opps": False,
    },
    "pro": {
        "label": "Pro", "price": 97,
        "max_domains": 3, "max_keywords": 200,
        "serp_depth": 100, "history_weeks": 12, "domain_opps": False,
    },
    "premium": {
        "label": "Premium", "price": 197,
        "max_domains": 5, "max_keywords": 500,
        "serp_depth": 100, "history_weeks": 12, "domain_opps": True,
    },
}

PLAN_ORDER = ["gratis", "basico", "pro", "premium"]
FREE_PLAN = "gratis"
PAID_STATUS = "active"

# Standardlänk till Hotmart-produkten (samma som tidigare i app.py)
_DEFAULT_CHECKOUT = "https://pay.hotmart.com/L106736067M"


def effective_plan(plan, status):
    """Planen som faktiskt gäller. Bara aktiva betalande får sin plan, alla andra får gratis."""
    p = str(plan or "").strip().lower()
    if status == PAID_STATUS and p in PLANS and p != FREE_PLAN:
        return p
    return FREE_PLAN


def get_plan(plan):
    """Returnerar plan-dict. Okänd plan ger gratis."""
    return PLANS.get(str(plan or "").strip().lower(), PLANS[FREE_PLAN])


def serp_depth(plan):
    """Antal Google-träffar att hämta för en plan."""
    return get_plan(plan)["serp_depth"]


def next_plan(plan):
    """Nästa plan uppåt, eller None om planen redan är högst."""
    p = str(plan or "").strip().lower()
    if p not in PLAN_ORDER:
        return PLAN_ORDER[1]
    i = PLAN_ORDER.index(p)
    return PLAN_ORDER[i + 1] if i + 1 < len(PLAN_ORDER) else None


def checkout_url(plan, email=None):
    """Hotmart-länk för en betald plan. Lägger till e-post om den finns."""
    url = os.environ.get(f"HOTMART_CHECKOUT_{str(plan).upper()}", "") or _DEFAULT_CHECKOUT
    if email:
        from urllib.parse import quote
        url += ("&" if "?" in url else "?") + "email=" + quote(email, safe="")
    return url

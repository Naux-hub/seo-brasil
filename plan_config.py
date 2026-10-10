"""
plan_config.py
==============
Hur djupt varje plan söker i Google (antal träffar som hämtas från DataForSEO).

DataForSEO tar betalt per 10 träffar. Top 30 kostar 30 % av top 100.
Gratis- och Básico-planerna hämtar top 30. Pro och Premium hämtar top 100.
Okänd eller saknad plan räknas som top 100, så befintliga kunder påverkas inte.
"""

PLAN_SERP_DEPTH = {
    "gratis": 30,
    "basico": 30,
    "pro": 100,
    "premium": 100,
}

DEFAULT_SERP_DEPTH = 100


def serp_depth(plan):
    """Returnerar antal Google-träffar att hämta för en plan."""
    if not plan:
        return DEFAULT_SERP_DEPTH
    return PLAN_SERP_DEPTH.get(str(plan).strip().lower(), DEFAULT_SERP_DEPTH)

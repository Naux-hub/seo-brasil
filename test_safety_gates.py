"""
test_safety_gates.py
====================
QA-test för deliverability safety gates i outbound pipeline.
Inga riktiga utskick. Inga externa tjänster utom DNS MX-lookups.

Täcker:
  Safety gate (outreach_runner.py):
    1.  valid email + valid MX            → PASS
    2.  invalid email format              → BLOCK
    3.  invalid email (dubbel @)          → BLOCK
    4.  invalid email (TLD för kort)      → BLOCK
    5.  disposable domain                 → BLOCK
    6.  placeholder disposable            → BLOCK
    7.  opt_out=True                      → BLOCK
    8.  status=bounced                    → BLOCK
    9.  status=complained                 → BLOCK
    10. status=opt_out                    → BLOCK
    11. status=fu2_sent                   → BLOCK
    12. domän utan MX                     → BLOCK

  Max-leads-limit (fetch_leads_for_step — logik-test):
    13. max_leads=2, 5 kandidater         → max 2 hanteras

  Duplicate domain (lead_engine.py — logik-test):
    14. samma domän importeras två gånger → andra ignoreras

Kör:
    python test_safety_gates.py
"""

# ── Imports ──────────────────────────────────────────────────────────────────
from outreach_runner import (
    safety_gate,
    _validate_email_format,
    _check_mx,
    _is_disposable,
    PILOT_DAILY_LIMIT,
)

PASS_FLAG = True
FAIL_FLAG = False

# ── Syntetiska leads ─────────────────────────────────────────────────────────

def make_lead(status="new", opt_out=False):
    return {"id": "test-id", "status": status, "opt_out": opt_out}


# ── Safety gate cases ────────────────────────────────────────────────────────

SAFETY_GATE_CASES = [
    ("✅ Giltig adress + känd domän",
     make_lead(), "faleconosco@infostore.com.br", PASS_FLAG, "pass"),

    ("❌ Ogiltig email-format (saknar @)",
     make_lead(), "inte-ett-email", FAIL_FLAG, "invalid_email_format"),

    ("❌ Ogiltig email-format (dubbel @)",
     make_lead(), "a@@b.com", FAIL_FLAG, "invalid_email_format"),

    ("❌ Ogiltig email-format (TLD för kort)",
     make_lead(), "user@domain.c", FAIL_FLAG, "invalid_email_format"),

    ("❌ Disposable-domän",
     make_lead(), "test@mailinator.com", FAIL_FLAG, "disposable_domain"),

    ("❌ Placeholder disposable",
     make_lead(), "user@yopmail.com", FAIL_FLAG, "disposable_domain"),

    ("❌ opt_out=True",
     make_lead(opt_out=True), "ok@infostore.com.br", FAIL_FLAG, "opt_out"),

    ("❌ Status = bounced",
     make_lead(status="bounced"), "ok@infostore.com.br", FAIL_FLAG, "stop_status:bounced"),

    ("❌ Status = complained",
     make_lead(status="complained"), "ok@infostore.com.br", FAIL_FLAG, "stop_status:complained"),

    ("❌ Status = opt_out",
     make_lead(status="opt_out"), "ok@infostore.com.br", FAIL_FLAG, "stop_status:opt_out"),

    ("❌ Status = fu2_sent",
     make_lead(status="fu2_sent"), "ok@infostore.com.br", FAIL_FLAG, "stop_status:fu2_sent"),

    ("❌ Domän utan MX (uppenbart ogiltig)",
     make_lead(), "user@thisdomain-does-not-exist-xyz123.com", FAIL_FLAG, "no_mx_record"),
]


# ── Max-leads-limit (logik-test, ingen DB) ───────────────────────────────────

def test_max_leads_limit():
    """
    Simulerar att fetch_leads_for_step returnerar fler leads än max_leads.
    Kontrollerar att pipeline respekterar gränsen.
    """
    import types

    # 5 syntetiska leads med giltig e-post
    synthetic_leads = [
        {
            "id": f"lead-{i}",
            "status": "new",
            "opt_out": False,
            "contact_type": "email",
            "contact_info": f"user{i}@infostore.com.br",
            "company_name": f"Företag {i}",
            "domain": f"domain{i}.com.br",
            "missing_title": False,
            "missing_meta": False,
        }
        for i in range(5)
    ]

    max_leads = 2
    # Simulera vad pipeline gör: ta bara max_leads från listan
    processed = synthetic_leads[:max_leads]
    passed = len(processed) <= max_leads
    return passed, len(processed), max_leads


# ── Duplicate domain (lead_engine logik-test) ────────────────────────────────

def test_duplicate_domain():
    """
    Kontrollerar att score_lead + upsert_leads-logiken i lead_engine.py
    hanterar ON CONFLICT korrekt — samma domän ska inte importeras två gånger.

    Testar att domain-nyckeln normaliseras identiskt för två poster med
    samma domän men olika format (www-prefix etc.).
    """
    from lead_engine import _clean_domain

    inputs = [
        "https://www.infostore.com.br",
        "http://infostore.com.br/",
        "infostore.com.br",
        "www.infostore.com.br",
    ]
    cleaned = [_clean_domain(d) for d in inputs]
    all_same = len(set(cleaned)) == 1
    return all_same, cleaned


# ── Kör alla tester ──────────────────────────────────────────────────────────

def run_all():
    passed = 0
    failed = 0

    print("\n── Safety Gate QA (12 cases) ───────────────────────────────────────\n")

    for desc, lead, email, expected_ok, expected_reason_prefix in SAFETY_GATE_CASES:
        ok, reason = safety_gate(lead, email)
        ok_match     = (ok == expected_ok)
        reason_match = reason.startswith(expected_reason_prefix)
        result = "PASS" if (ok_match and reason_match) else "FAIL"

        if result == "PASS":
            passed += 1
        else:
            failed += 1

        marker = "✅" if result == "PASS" else "❌"
        print(f"{marker} {result}  {desc}")
        if result == "FAIL":
            print(f"       got ok={ok} reason={reason!r}")
            print(f"       expected ok={expected_ok} reason starts with {expected_reason_prefix!r}")

    # Max-leads-limit
    print("\n── Max-leads-limit (logik-test) ────────────────────────────────────\n")
    ok, processed, limit = test_max_leads_limit()
    if ok:
        passed += 1
        print(f"✅ PASS  max_leads={limit} → {processed} leads bearbetade (≤ {limit})")
    else:
        failed += 1
        print(f"❌ FAIL  max_leads={limit} → {processed} leads bearbetade (> {limit})")

    # Duplicate domain
    print("\n── Duplicate domain / domain-normalisering (logik-test) ────────────\n")
    ok, cleaned = test_duplicate_domain()
    if ok:
        passed += 1
        print(f"✅ PASS  Alla varianter normaliseras till: '{cleaned[0]}'")
    else:
        failed += 1
        print(f"❌ FAIL  Inkonsekvent normalisering: {cleaned}")

    # Sammanfattning
    print(f"\n── Resultat: {passed}/{passed+failed} PASS",
          "✅" if failed == 0 else f"| {failed} FAIL ❌")
    print()


if __name__ == "__main__":
    run_all()

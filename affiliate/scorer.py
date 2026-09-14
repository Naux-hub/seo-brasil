"""
affiliate/scorer.py
====================
Affiliate Prospecting Machine v0.1 — SEO Brasil
Calibration MVP: AI-powered scoring of affiliate candidates.

Usage:
    # Score a single candidate file:
    python scorer.py prospects/br/joao_silva.json

    # Score all candidates in the prospects/br/ directory:
    python scorer.py --all

    # Print report to stdout instead of saving:
    python scorer.py prospects/br/joao_silva.json --print

Requirements:
    pip install anthropic python-dotenv --break-system-packages

API key:
    Set ANTHROPIC_API_KEY in .env (see .env.example)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # .env loading optional — can also set env var directly

# Fallback: read from .streamlit/secrets.toml if ANTHROPIC_API_KEY not yet set
if not os.environ.get("ANTHROPIC_API_KEY"):
    _secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    if _secrets_path.exists():
        try:
            import tomllib
            with open(_secrets_path, "rb") as _f:
                _secrets = tomllib.load(_f)
            _key = _secrets.get("ANTHROPIC_API_KEY") or _secrets.get("anthropic_api_key")
            if _key:
                os.environ["ANTHROPIC_API_KEY"] = str(_key).strip()
        except Exception:
            pass

try:
    import anthropic
except ImportError:
    print("anthropic saknas. Kör: pip install anthropic --break-system-packages", file=sys.stderr)
    sys.exit(1)

# Import score model from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from score_model import SCORE_MODEL, get_classification

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

CANDIDATES_DIR = Path(__file__).parent / "prospects" / "br"
REPORTS_DIR = Path(__file__).parent / "reports" / "br"
MODEL = "claude-haiku-4-5-20251001"  # Fast + cheap for calibration; swap to sonnet for production

# ---------------------------------------------------------------------------
# PROMPT BUILDER
# ---------------------------------------------------------------------------

def _build_scoring_criteria_text() -> str:
    """Format the full scoring model as readable text for the prompt."""
    lines = [
        f"AFFILIATE SCORE v{SCORE_MODEL['version']} — SEO Brasil",
        f"Total: {SCORE_MODEL['total_points']} poäng\n",
        "KNOCKOUT-FILTER (applicera FÖRE scoring — om något stämmer → knocked_out: true):",
    ]
    for f in SCORE_MODEL["knockout_filters"]:
        lines.append(f"  - {f}")

    lines.append("\nSCORING-KATEGORIER:\n")

    for cat in SCORE_MODEL["categories"]:
        lines.append(f"{cat['emoji']} {cat['name']} — max {cat['max_points']} poäng")
        lines.append(f"   Regel: {cat['rule']}")
        lines.append("   Nivåer:")
        for lvl in cat["levels"]:
            lines.append(f"     {lvl['points']}p: {lvl['description']}")
        lines.append("   Observerbara signaler:")
        for sig in cat["observable_signals"]:
            lines.append(f"     · {sig}")
        lines.append("")

    lines.append("KLASSIFICERING:")
    for cls in SCORE_MODEL["classification"]:
        lines.append(f"  {cls['min']}–{cls['max']} → {cls['grade']}: {cls['label']}")

    return "\n".join(lines)


def _build_product_test_criteria_text() -> str:
    """Format product test potential criteria for the prompt.
    This is a SEPARATE signal from Affiliate Score v1.2 — it does not affect total_score or grade.
    """
    return """PRODUCT TEST POTENTIAL — Oberoende signal (påverkar INTE Affiliate Score v1.2)
=======================================================================
Bedöm hur lämplig kandidaten är att testa SEO Brasil som produkt.
OBS: Denna bedömning är HELT OBEROENDE från affiliate-graden ovan.

NIVÅER:
  VERY HIGH — Stark SEO-publik (t.ex. SEO-byrå, SEO-konsult), aktiv online-närvaro,
              skapar innehåll om verktyg/mjukvara, tydlig SEO-fokuserad målgrupp.
  HIGH      — Digital marknadsföringspublik med SEO-intresse, viss innehållsproduktion,
              viss online-räckvidd, kan ha nytta av SEO-verktyg.
  MEDIUM    — Generell digital marknadsförings- eller affärspublik, begränsat SEO-fokus,
              SEO-verktyg kan vara relevant men är inte kärnan.
  LOW       — Orelaterad publik, låg räckvidd, ingen innehållsproduktion,
              eller tydligt utanför SEO/digital marknadsföring.

OBSERVERBARA SIGNALER (basera ENBART på data i kandidatprofilen):
  · Nämner SEO, rankningar, organisk trafik eller sökmotoroptimering
  · Har en byrå, konsultverksamhet eller utbildning inom SEO/digital marknadsföring
  · Skapar innehåll (blogg, YouTube, podcast, nyhetsbrev) om digitala verktyg
  · Har kunder eller följare som arbetar med SEO eller digital marknadsföring
  · Driver en SEO-relaterad produkt eller tjänst
  · Är aktiv på LinkedIn, Twitter/X, eller har en webbplats med SEO-innehåll

VIKTIGT — Evidence over Assumption:
  · Ange BARA vad som framgår ur kandidatdatan — spekulera ALDRIG om publik-storlek,
    antal följare eller affiliate-aktivitet om det inte finns i profilen.
  · Om underlag saknas → välj LOW och förklara vad som saknas."""


def build_prompt(candidate: dict) -> str:
    criteria = _build_scoring_criteria_text()
    product_test_criteria = _build_product_test_criteria_text()

    candidate_text = json.dumps(candidate, ensure_ascii=False, indent=2)

    return f"""Du är ett AI-system som bedömer potentiella affiliates för SEO Brasil — ett brasilianskt SEO-rankingverktyg (R$197/mån, 30% recurring provision via Hotmart).

SCORING-MODELL:
{criteria}

{product_test_criteria}

KANDIDAT ATT BEDÖMA:
{candidate_text}

INSTRUKTIONER:
1. Tillämpa knockout-filter FÖRST. Om kandidaten knockas ut → sätt knocked_out: true, ange orsak, sätt alla scores till 0.
2. Om inte utslagen → score varje kategori exakt enligt nivåerna ovan.
3. Använd ONLY observerbara signaler från kandidatdata. Spekulera INTE.
4. Om underlag saknas för en kategori → sätt insufficient_evidence: true och följ kategorins regel om max-poäng.
5. Motivera varje score med konkreta bevis från kandidatdatan.
6. Räkna ihop total score.
7. Ge en outreach-vinkel på brasiliansk portugisiska — en specifik pitch baserad på kandidatens faktiska profil.
8. Bedöm product_test_potential SEPARAT och OBEROENDE från affiliate-graden. Basera ENBART på observerbara signaler i kandidatdatan — spekulera aldrig om publik-storlek eller följare.

Svara ENDAST med giltig JSON enligt detta schema (ingen text utanför JSON):

{{
  "candidate_name": "<namn>",
  "knocked_out": false,
  "knockout_reason": null,
  "categories": {{
    "target_audience_fit": {{
      "score": <int>,
      "max": 30,
      "insufficient_evidence": false,
      "evidence": "<konkret motivering baserad på kandidatdata>"
    }},
    "seo_relevance": {{
      "score": <int>,
      "max": 20,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }},
    "purchase_influence": {{
      "score": <int>,
      "max": 15,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }},
    "reach_quality": {{
      "score": <int>,
      "max": 10,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }},
    "customer_volume_potential": {{
      "score": <int>,
      "max": 10,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }},
    "brazil_fit": {{
      "score": <int>,
      "max": 5,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }},
    "affiliate_fit": {{
      "score": <int>,
      "max": 5,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }},
    "content_traffic_potential": {{
      "score": <int>,
      "max": 5,
      "insufficient_evidence": false,
      "evidence": "<motivering>"
    }}
  }},
  "total_score": <int>,
  "grade": "<A+|A|B|C|Skip>",
  "grade_label": "<klassificeringsetikett>",
  "why_interesting": "<2–3 meningar på svenska: varför är den här personen intressant för SEO Brasil?>",
  "outreach_angle": "<1–2 meningar på brasiliansk portugisiska: specifik pitch anpassad till kandidatens profil>",
  "product_test_potential": "<VERY HIGH|HIGH|MEDIUM|LOW>",
  "product_test_evidence": "<observerade fakta från kandidatdatan — ange BARA vad som faktiskt framgår, spekulera inte>",
  "product_test_reason": "<motivering till vald nivå baserad på signalerna ovan>",
  "recommended_action": "<konkret rekommenderad åtgärd för SEO Brasil, t.ex. 'Skicka testlicens direkt' eller 'Avvakta tills mer data finns'>"
}}"""


# ---------------------------------------------------------------------------
# SCORER
# ---------------------------------------------------------------------------

def score_candidate(candidate: dict) -> dict:
    """Call Claude API to score a candidate. Returns parsed result dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Debug: show what keys exist in secrets.toml
        _sp = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
        if _sp.exists():
            try:
                import tomllib
                with open(_sp, "rb") as _f:
                    _s = tomllib.load(_f)
                print(f"\n  DEBUG secrets.toml top-level keys: {list(_s.keys())}")
                for _k, _v in _s.items():
                    if isinstance(_v, dict):
                        print(f"  DEBUG [{_k}] sub-keys: {list(_v.keys())}")
            except Exception as e:
                print(f"\n  DEBUG secrets.toml parse error: {e}")
        else:
            print(f"\n  DEBUG secrets.toml not found at: {_sp}")
        raise RuntimeError(
            "ANTHROPIC_API_KEY saknas. Lägg till den i .env eller sätt miljövariabeln."
        )

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(candidate)

    message = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # Validate + fix total_score (recalculate to be safe)
    if not result.get("knocked_out"):
        computed_total = sum(
            result["categories"][cat["id"]]["score"]
            for cat in SCORE_MODEL["categories"]
            if cat["id"] in result.get("categories", {})
        )
        result["total_score"] = computed_total
        cls = get_classification(computed_total)
        result["grade"] = cls["grade"]
        result["grade_label"] = cls["label"]

    # Validate + pass through product_test_potential fields (independent of affiliate score)
    _valid_ptp = {"VERY HIGH", "HIGH", "MEDIUM", "LOW"}
    _ptp = str(result.get("product_test_potential", "")).upper().strip()
    if _ptp not in _valid_ptp:
        result["product_test_potential"] = "LOW"
        result["product_test_evidence"] = "Insufficient data to assess product test potential."
        result["product_test_reason"] = "Fallback: level could not be determined from API response."
        result["recommended_action"] = "Review manually before sending test license."
    else:
        result["product_test_potential"] = _ptp
        # Ensure all 3 companion fields exist; fill fallback if absent
        if not result.get("product_test_evidence"):
            result["product_test_evidence"] = "No evidence text returned by model."
        if not result.get("product_test_reason"):
            result["product_test_reason"] = "No reasoning text returned by model."
        if not result.get("recommended_action"):
            result["recommended_action"] = "No recommended action returned by model."

    return result


# ---------------------------------------------------------------------------
# REPORT FORMATTER
# ---------------------------------------------------------------------------

def format_report(candidate: dict, result: dict) -> str:
    """Format a human-readable markdown report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    name = result.get("candidate_name", candidate.get("name", "Unknown"))

    lines = [
        f"# Affiliate Score Report — {name}",
        f"*Genererad: {now} | Modell: {MODEL} | Score v{SCORE_MODEL['version']}*\n",
    ]

    if result.get("knocked_out"):
        lines += [
            "## ❌ KNOCKOUT",
            f"**Anledning:** {result.get('knockout_reason', 'Ej angiven')}",
            "\nKandidaten uppfyller inte grundkraven. Ingen vidare scoring utförd.",
        ]
        return "\n".join(lines)

    total = result.get("total_score", 0)
    grade = result.get("grade", "?")
    grade_label = result.get("grade_label", "")

    # Grade emoji
    grade_emoji = {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "Skip": "🔴"}.get(grade, "⚪")

    lines += [
        f"## {grade_emoji} Total Score: {total}/100 — {grade}",
        f"**{grade_label}**\n",
        "## Kandidatdata",
        f"- **Namn:** {candidate.get('name', '—')}",
        f"- **Typ:** {candidate.get('type', '—')}",
        f"- **Plattform:** {candidate.get('platform', '—')}",
        f"- **URL:** {candidate.get('url', '—')}",
        f"- **Företag/byrå:** {candidate.get('company', '—')}",
        "",
        "## Scoring per kategori\n",
    ]

    cats = result.get("categories", {})
    for cat_def in SCORE_MODEL["categories"]:
        cat_id = cat_def["id"]
        cat_data = cats.get(cat_id, {})
        score = cat_data.get("score", 0)
        max_p = cat_def["max_points"]
        evidence = cat_data.get("evidence", "—")
        insuf = cat_data.get("insufficient_evidence", False)
        insuf_tag = " ⚠️ *insufficient evidence*" if insuf else ""

        lines += [
            f"### {cat_def['emoji']} {cat_def['name']}: {score}/{max_p}{insuf_tag}",
            f"{evidence}\n",
        ]

    ptp = result.get("product_test_potential", "—")
    ptp_emoji = {"VERY HIGH": "🟢", "HIGH": "🟡", "MEDIUM": "🟠", "LOW": "🔴"}.get(ptp, "⚪")

    lines += [
        "## Varför intressant",
        result.get("why_interesting", "—"),
        "",
        "## Rekommenderad outreach-vinkel",
        f"*{result.get('outreach_angle', '—')}*",
        "",
        "---",
        "",
        f"## 🧪 Product Test Potential: {ptp_emoji} {ptp}",
        f"> *(Oberoende signal — påverkar inte Affiliate Score v1.2)*",
        "",
        f"**Underlag:** {result.get('product_test_evidence', '—')}",
        "",
        f"**Motivering:** {result.get('product_test_reason', '—')}",
        "",
        f"**Rekommenderad åtgärd:** {result.get('recommended_action', '—')}",
        "",
        "---",
        f"*SEO Brasil Affiliate Prospecting Machine v0.1*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FILE I/O
# ---------------------------------------------------------------------------

def load_candidate(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_report(name: str, result: dict, report_md: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    slug = name.lower().replace(" ", "_").replace("/", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = REPORTS_DIR / f"{slug}_{ts}.json"
    md_path = REPORTS_DIR / f"{slug}_{ts}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def process_file(path: Path, print_only: bool = False) -> dict:
    """Score one candidate file and return the result."""
    candidate = load_candidate(path)
    print(f"  Scoring {candidate.get('name', path.stem)}...", end=" ", flush=True)

    result = score_candidate(candidate)
    report_md = format_report(candidate, result)

    total = result.get("total_score", 0)
    grade = result.get("grade", "?")
    knocked = result.get("knocked_out", False)

    if knocked:
        print(f"KNOCKOUT — {result.get('knockout_reason', '')}")
    else:
        ptp = result.get("product_test_potential", "?")
        print(f"{total}/100 — {grade} | PTP: {ptp}")

    if print_only:
        print("\n" + report_md)
    else:
        md_path = save_report(candidate.get("name", path.stem), result, report_md)
        print(f"  → Rapport sparad: {md_path.name}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="SEO Brasil — Affiliate Scorer v0.1"
    )
    parser.add_argument(
        "candidate_file",
        nargs="?",
        help="Sökväg till kandidat-JSON-fil (t.ex. candidates/joao_silva.json)",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help=f"Score alla .json-filer i {CANDIDATES_DIR}/",
    )
    parser.add_argument(
        "--print", "-p",
        action="store_true",
        dest="print_only",
        help="Skriv ut rapport till stdout istället för att spara fil",
    )
    args = parser.parse_args()

    if not args.all and not args.candidate_file:
        parser.print_help()
        sys.exit(1)

    if args.all:
        files = sorted(CANDIDATES_DIR.glob("*.json"))
        # Skip template
        files = [f for f in files if f.stem != "template"]
        if not files:
            print(f"Inga kandidatfiler hittades i {CANDIDATES_DIR}/")
            sys.exit(0)
        print(f"\nScoring {len(files)} kandidater...\n")
        results = []
        for f in files:
            try:
                r = process_file(f, print_only=args.print_only)
                results.append(r)
            except Exception as e:
                print(f"  FEL: {e}")
        # Summary
        print("\n--- SAMMANFATTNING ---")
        for r in results:
            name = r.get("candidate_name", "?")
            if r.get("knocked_out"):
                print(f"  ❌ {name}: KNOCKOUT")
            else:
                g = r.get("grade", "?")
                t = r.get("total_score", 0)
                emoji = {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "Skip": "🔴"}.get(g, "⚪")
                ptp = r.get("product_test_potential", "?")
                print(f"  {emoji} {name}: {t}/100 — {g} | PTP: {ptp}")
    else:
        path = Path(args.candidate_file)
        if not path.exists():
            print(f"Fil hittades inte: {path}", file=sys.stderr)
            sys.exit(1)
        process_file(path, print_only=args.print_only)


if __name__ == "__main__":
    main()

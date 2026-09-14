# Affiliate Prospecting Engine — Architecture
**Last updated:** 2026-09-14
**Status:** Production (BR active, MX planned)

---

## Purpose

This folder contains the affiliate prospecting engine for SEO Brasil.
It is a standalone system for finding, scoring, and preparing outreach to potential affiliate partners.

It is completely separate from:
- The SEO Brasil production app (`rank_tracker.py`, `weekly_report.py`, `onboarding.py`, etc.)
- The e-commerce outbound lead pipeline (`lead_engine.py`, `outreach_runner.py`)

---

## Workflow

```
1. Add prospect JSON to prospects/br/
2. Run scorer:  python scorer.py prospects/br/<candidate>.json
3. Report saved to reports/br/
4. Review: grade + Product Test Potential
5. Draft outreach in outreach/pending/
6. Human approves and sends manually
7. Move sent records to outreach/sent/
```

Future (Mexico):
```
1. Add prospect JSON to prospects/mx/
2. Run: python scorer.py prospects/mx/<candidate>.json
   (reports saved to reports/mx/)
```

---

## Folder structure

```
affiliate/
│
├── scorer.py             ← CANONICAL entry point (v1.3)
├── score_model.py        ← LOCKED scoring model (v1.2)
├── test_scorer.py        ← Test suite (36 tests)
├── markets.py            ← Market configuration (BR active, MX planned)
├── ARCHITECTURE.md       ← This file
│
├── prospects/
│   ├── template.json     ← Candidate JSON schema / template
│   ├── br/               ← Brazil prospects (active)
│   │   └── *.json
│   └── mx/               ← Mexico prospects (future, empty)
│
├── reports/
│   ├── br/               ← Brazil scored reports (.json + .md)
│   │   └── *_YYYYMMDD_HHMMSS.json
│   └── mx/               ← Mexico reports (future, empty)
│
└── outreach/
    ├── OUTREACH_CAMPANHA_2026.md   ← Campaign history
    ├── RELATORIO_PROSPECCAO_2026.md ← Prospecting run history
    ├── pending/          ← Approved drafts awaiting manual send
    └── sent/             ← Archive after sending
```

---

## Canonical files

| File | Role | Status |
|---|---|---|
| `scorer.py` | Entry point — calls Claude API, applies score model, outputs reports | ✅ Active v1.3 |
| `score_model.py` | Scoring weights, criteria, classification — source of truth | 🔒 LOCKED v1.2 |
| `test_scorer.py` | Full test suite — run before and after any scorer change | ✅ 36/36 |
| `markets.py` | Market config (BR/MX) — product details, paths, status | ✅ Active |

---

## Scorer responsibilities

`scorer.py` does exactly three things:

1. **Loads** a candidate JSON from `prospects/<market>/`
2. **Scores** using the Claude API + `score_model.py` criteria
3. **Outputs** a structured report to `reports/<market>/`

It does NOT:
- Send emails or messages
- Manage outreach sequences
- Write to any database
- Know anything about the production app

---

## Score model (LOCKED)

`score_model.py` v1.2 is the source of truth for all scoring logic.

**DO NOT modify** weights, point values, knockout filters, or classification thresholds
without explicit approval and a version bump (v1.2 → v1.3).

The model is intentionally isolated so the scorer can be rebuilt around it.

Current model:
- 8 scoring categories, 100 points total
- 4 knockout filters (auto-disqualify)
- Grades: A+ (90–100), A (75–89), B (55–74), C (35–54), Skip (0–34)

---

## Product Test Potential (PTP)

PTP is a separate signal added in scorer v1.3. It does NOT affect total_score or grade.

Levels: VERY HIGH / HIGH / MEDIUM / LOW

PTP answers: "How suitable is this person to receive a product test license?"
It is independent from the affiliate score.

---

## Running the scorer

From inside `affiliate/`:

```bash
# Score one prospect
python scorer.py prospects/br/amanda_noronha.json

# Score all BR prospects
python scorer.py --all

# Print report to stdout (no file saved)
python scorer.py prospects/br/amanda_noronha.json --print
```

Requires: `ANTHROPIC_API_KEY` in `.env` (project root) or environment variable.

---

## Market configuration

`markets.py` holds market-specific details (product name, currency, platform, paths).
The scoring model itself is market-agnostic.

To add Mexico prospects: place candidate JSONs in `prospects/mx/`.
Reports will save to `reports/mx/`.
Full `--market mx` flag support is planned but not yet implemented.

---

## Outreach folder

`outreach/` is for human-reviewed outreach only. Nothing is sent automatically.

- `pending/` — approved drafts, not yet sent
- `sent/` — archive after manual sending

---

## What must NOT change casually

| File | Why |
|---|---|
| `score_model.py` | All historical scores are based on v1.2. Changing weights invalidates comparisons. |
| `scorer.py` scoring logic | Any change must be tested against all 36 tests |
| `prospects/br/*.json` | Historical candidate data — do not edit after scoring |
| `reports/br/*.json` | Scored output — do not edit; source of truth for decisions made |

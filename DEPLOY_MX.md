# Viva Mexico — Deployment Guide (seomexico.app)

**Phase 1 — Technical Foundation**
Branch: `viva-mexico-phase-1`
Last updated: 2026-09-16

---

## Prerequisites

Before deploying, complete these steps **in order**:

1. Run the Supabase migration (adds `market` column)
2. Create a new Railway service
3. Point `seomexico.app` domain to Railway
4. Configure environment variables
5. Deploy

---

## Step 1 — Supabase Migration

Run `migrations/add_market_column.sql` in the Supabase SQL editor
(project: same Supabase project as SEO Brasil).

```sql
-- Paste contents of migrations/add_market_column.sql
-- Takes ~1 second. Safe to run while Brazil is live.
```

**Verify:**
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name IN ('subscribers','tracked_keywords','keyword_rankings')
  AND column_name = 'market'
ORDER BY table_name;
-- Expected: 3 rows, data_type='text', column_default='br'
```

---

## Step 2 — Railway Service

1. Go to [railway.app](https://railway.app) → your project
2. Click **+ New Service** → **GitHub Repo**
3. Select the `seo-brasil` repo, branch `viva-mexico-phase-1`
4. Set the **start command**:
   ```
   streamlit run app_mexico_new.py --server.port $PORT --server.headless true
   ```
5. Do NOT use the same service as Brazil — they must be separate Railway services

---

## Step 3 — Domain

1. In Railway service settings → **Domains** → **Add custom domain**
2. Enter: `seomexico.app`
3. Add the CNAME record your DNS provider requires (Railway shows it)
4. Wait for SSL provisioning (~5 minutes)

---

## Step 4 — Environment Variables

In the Railway service for Mexico, set:

| Variable | Value | Notes |
|---|---|---|
| `SUPABASE_URL` | same as Brazil | shared DB project |
| `SUPABASE_KEY` | same as Brazil (anon key) | |
| `SUPABASE_SERVICE_KEY` | same as Brazil | needed for admin user creation |
| `DATAFORSEO_LOGIN` | same as Brazil | shared DataForSEO account |
| `DATAFORSEO_PASSWORD` | same as Brazil | |
| `RESEND_API_KEY` | same as Brazil | for onboarding emails (future) |
| `MARKET` | `mx` | tells rank_tracker + keyword_cache to use Mexico |
| `HOTMART_MX_URL` | TBD | set when MX Hotmart product is ready |

> **Note:** Brazil's Railway service does NOT need a `MARKET` variable —
> it defaults to `br` automatically.

Also create a `.streamlit/secrets.toml` equivalent in the Railway service
(Railway uses env vars, not secrets.toml — the app reads `st.secrets["..."]`
which maps to env vars in production).

---

## Step 5 — GitHub Actions for Mexico

Two new workflow files are needed for MX (copy from BR workflows and add `MARKET: mx`):

### weekly_seo_report_mx.yml
```yaml
name: Weekly SEO Report — Mexico

on:
  schedule:
    - cron: "0 7 * * 1"   # Monday 07:00 UTC
  workflow_dispatch:

jobs:
  run-report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install supabase requests
      - name: Run rank tracker (MX)
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          DATAFORSEO_LOGIN: ${{ secrets.DATAFORSEO_LOGIN }}
          DATAFORSEO_PASSWORD: ${{ secrets.DATAFORSEO_PASSWORD }}
          MARKET: mx
        run: python rank_tracker.py
```

> Create this file in `.github/workflows/` before Phase 2 launch.

---

## Step 6 — Seed keyword cache

After deployment, warm up the Mexico keyword cache:

```bash
# From the seo-brasil repo root
MARKET=mx python seed_cache_mx.py --dry-run   # preview first
MARKET=mx python seed_cache_mx.py             # run for real (~$1.80 one-time cost)
```

---

## Architecture summary

```
seobrasil.app  → Railway service A → app_brasil_new.py  (MARKET=br, default)
seomexico.app  → Railway service B → app_mexico_new.py  (MARKET=mx)

Both services → same Supabase project (shared DB)
Both services → same DataForSEO account
Both services → same GitHub repo (different entry points)

rank_tracker.py   → reads MARKET env var, routes to correct location_code
keyword_cache.py  → reads MARKET env var, routes to correct location_code
```

---

## What is NOT in Phase 1

- MX onboarding emails (needs Resend template in Spanish)
- Hotmart MX product (needs pricing decision)
- weekly_report.py for MX (needs Spanish email template)
- MX affiliate prospecting (future)

---

## Rollback plan

If something breaks:
1. Brazil is on a separate Railway service — it is unaffected
2. To roll back MX: redeploy Railway service B from `main` branch (or delete it)
3. The `market` column in Supabase is backward-compatible — Brazil rows have `market='br'` via default

---

## Verification checklist

Before calling Phase 1 done:

- [ ] Migration ran successfully (3 rows in verification query)
- [ ] `app_brasil_new.py` unchanged (git diff confirms no changes)
- [ ] `rank_tracker.py` with `MARKET=br` behaves identically to before
- [ ] `keyword_cache.py` with `MARKET=br` behaves identically to before
- [ ] `app_mexico_new.py` renders in local Streamlit with MX config
- [ ] `market_config.py` returns correct values for br and mx
- [ ] `seed_cache_mx.py --dry-run` lists expected keywords
- [ ] Railway service B created and responding at seomexico.app

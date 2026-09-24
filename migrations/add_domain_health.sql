-- =============================================================================
-- Migration: add_domain_health.sql
-- Domain Rank + Spam Score per prenumerant (Kildary Feedback V2)
-- Date: 2026-09-24
-- =============================================================================
--
-- Lägger till tre kolumner i subscribers-tabellen:
--   domain_rank         INTEGER   — DataForSEO Domain Rank (0–100), NULL = ej hämtat
--   spam_score          INTEGER   — DataForSEO Spam Score (0–100), NULL = ej tillgänglig
--   domain_enriched_at  TIMESTAMPTZ — Tidpunkt för senaste hämtning, NULL = aldrig hämtat
--
-- Säker att köra mot live-databasen:
--   - ADD COLUMN IF NOT EXISTS är idempotent och icke-destruktiv
--   - Inga befintliga rader eller kolumner ändras
--   - Alla befintliga rader får NULL i de nya kolumnerna (korrekt starttillstånd)
--   - DR=0 lagras som 0, INTE som NULL (0 är ett giltigt värde)
--   - SS=NULL lagras som NULL (domänen saknas i DataForSEO-svaret)
--
-- Kör i Supabase SQL Editor:
--   Klistra in och kör detta script. Idempotent — kan köras flera gånger utan problem.
-- =============================================================================

ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS domain_rank        INTEGER,
  ADD COLUMN IF NOT EXISTS spam_score         INTEGER,
  ADD COLUMN IF NOT EXISTS domain_enriched_at TIMESTAMPTZ;

-- Index för framtida batch-refresh (weekly_domain_refresh.py)
-- Hittar snabbt prenumeranter med domän som behöver en uppdatering
CREATE INDEX IF NOT EXISTS idx_subscribers_domain_enriched_at
  ON subscribers (domain_enriched_at)
  WHERE domain IS NOT NULL;

-- =============================================================================
-- Verifiering — kör efter migration för att bekräfta att kolumnerna finns
-- =============================================================================
--
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'subscribers'
--   AND column_name IN ('domain_rank', 'spam_score', 'domain_enriched_at')
-- ORDER BY column_name;
--
-- Förväntat resultat (3 rader):
--   domain_enriched_at  timestamp with time zone  YES
--   domain_rank         integer                   YES
--   spam_score          integer                   YES
-- =============================================================================

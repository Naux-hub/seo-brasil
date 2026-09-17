-- =============================================================================
-- Migration: add_market_column.sql
-- Phase 1 — Viva Mexico
-- Date: 2026-09-16
-- =============================================================================
--
-- Adds a 'market' column (TEXT NOT NULL DEFAULT 'br') to three tables.
-- All existing Brazil rows automatically receive market='br' via the default
-- before the NOT NULL constraint is applied — safe in PostgreSQL 12+.
-- No data is deleted or modified. Safe to run while Brazil is live.
--
-- Run this in the Supabase SQL editor BEFORE deploying app_mexico_new.py.
--
-- Idempotent: uses IF NOT EXISTS on all statements.
-- =============================================================================

-- 1. subscribers
ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'br';

-- 2. tracked_keywords
ALTER TABLE tracked_keywords
  ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'br';

-- 3. keyword_rankings
ALTER TABLE keyword_rankings
  ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'br';

-- =============================================================================
-- Verification — run after migration to confirm columns exist
-- =============================================================================
--
-- SELECT table_name, column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE table_name IN ('subscribers','tracked_keywords','keyword_rankings')
--   AND column_name = 'market'
-- ORDER BY table_name;
--
-- Expected: 3 rows
--   data_type    = text
--   column_default = 'br'::text
--   is_nullable  = NO
--
-- Also verify existing BR rows got the default:
-- SELECT market, count(*) FROM subscribers GROUP BY market;
-- Expected: only 'br' rows (no NULL, no other market yet)
-- =============================================================================

-- Optional indexes (run separately if needed):
-- CREATE INDEX IF NOT EXISTS idx_subscribers_market ON subscribers(market);
-- CREATE INDEX IF NOT EXISTS idx_tracked_keywords_market ON tracked_keywords(market);
-- CREATE INDEX IF NOT EXISTS idx_keyword_rankings_market ON keyword_rankings(market);

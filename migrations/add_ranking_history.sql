-- =============================================================================
-- Migration: add_ranking_history.sql
-- Date: 2026-09-26
-- =============================================================================
--
-- 1. Creates keyword_rankings_history — INSERT-only historical log.
--    Never upserted. Each weekly run and each onboarding adds a new row.
--
-- 2. Adds plan column to subscribers.
--    Existing rows receive 'pro' by default.
--    Set to 'premium' manually when a user upgrades (until billing is wired).
--
-- Idempotent: safe to re-run (IF NOT EXISTS / IF NOT EXISTS guards).
-- Run in Supabase SQL Editor before deploying ranking history feature.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. keyword_rankings_history
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS keyword_rankings_history (
    id            bigserial PRIMARY KEY,
    user_id       uuid         NOT NULL,
    keyword       text         NOT NULL,
    domain        text         NOT NULL,
    rank_position int,                       -- NULL = not in top 100 (valid data)
    checked_at    timestamptz  NOT NULL,
    market        text         NOT NULL DEFAULT 'br',
    source        text         NOT NULL DEFAULT 'weekly'  -- 'weekly' | 'initial'
);

-- Index: fast lookup per user / keyword / domain ordered by date
CREATE INDEX IF NOT EXISTS idx_krh_lookup
    ON keyword_rankings_history (user_id, keyword, domain, checked_at DESC);

-- ---------------------------------------------------------------------------
-- 2. plan column on subscribers
-- ---------------------------------------------------------------------------

ALTER TABLE subscribers
    ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'pro';

-- ---------------------------------------------------------------------------
-- Verification queries — run after migration to confirm success
-- ---------------------------------------------------------------------------
--
-- Confirm history table exists with correct columns:
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'keyword_rankings_history'
-- ORDER BY ordinal_position;
--
-- Confirm plan column on subscribers:
-- SELECT plan, COUNT(*) FROM subscribers GROUP BY plan;
-- Expected: only 'pro' rows (all existing subscribers got the default)
--
-- Confirm index was created:
-- SELECT indexname FROM pg_indexes WHERE tablename = 'keyword_rankings_history';
-- Expected: idx_krh_lookup
-- =============================================================================

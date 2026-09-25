-- Migration: lägg till ahrefs_dr-kolumn i subscribers
-- Datum: 2026-09-25
-- Syfte: lagra Ahrefs Domain Rating (float 0–100) separat från DataForSEO Domain Rank
-- Kör en gång i Supabase SQL Editor

ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS ahrefs_dr NUMERIC;

-- Kommentar: NULL = ej hämtat ännu, 0.0 = hämtat men Ahrefs returnerade 0 (ingen backlinkdata)

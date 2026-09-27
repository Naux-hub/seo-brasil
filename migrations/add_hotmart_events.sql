-- =============================================================================
-- Migration: add_hotmart_events.sql
-- Date: 2026-09-26
-- =============================================================================
-- Skapar hotmart_events — idempotency-logg och audit trail för Hotmart-webhooks.
--
-- UNIQUE(transaction_id, event): samma transaktion kan ha flera events,
-- t.ex. PURCHASE_COMPLETE → PURCHASE_REFUNDED på samma transaction_id.
--
-- RLS aktiverat utan policy = ingen åtkomst via anon/authenticated.
-- Webhooken använder service role key och bypasser RLS.
--
-- Idempotent: säker att köra igen (IF NOT EXISTS).
-- Kör i Supabase SQL Editor innan hotmart-webhook-funktionen aktiveras.
-- =============================================================================

CREATE TABLE IF NOT EXISTS hotmart_events (
    id               bigserial    PRIMARY KEY,
    transaction_id   text         NOT NULL,
    event            text         NOT NULL,
    email            text,
    offer_code       text,
    subscriber_found boolean,
    processed_at     timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT hotmart_events_tx_event_unique UNIQUE (transaction_id, event)
);

CREATE INDEX IF NOT EXISTS idx_hotmart_events_email
    ON hotmart_events (email);

CREATE INDEX IF NOT EXISTS idx_hotmart_events_processed_at
    ON hotmart_events (processed_at DESC);

-- RLS: ingen policy = ingen klientåtkomst; service role bypasser RLS
ALTER TABLE hotmart_events ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Verifieringsfrågor — kör efter migrering
-- =============================================================================
-- SELECT COUNT(*) FROM hotmart_events;
-- Förväntat: 0 (tom tabell, inga webhook-events ännu)
--
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'hotmart_events'
-- ORDER BY ordinal_position;
-- Förväntat: 7 kolumner (id, transaction_id, event, email, offer_code,
--            subscriber_found, processed_at)
-- =============================================================================

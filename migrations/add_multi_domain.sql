-- =============================================================================
-- Migration: add_multi_domain.sql
-- Date: 2026-09-26
-- =============================================================================
-- Lägger till stöd för multi-domain (Premium: upp till 5 domäner, 300 keywords totalt).
--
-- 1. Skapar user_domains — spårar aktiva domäner per användare.
--    UNIQUE(user_id, domain): pausade domäner sätts is_active=false, raderas aldrig.
--
-- 2. Lägger till domain-kolumn (nullable) på tracked_keywords.
--    Nullable först — NOT NULL läggs till efter att data migrerats och verifierats.
--
-- 3. Migrerar befintliga subscribers.domain → user_domains.
-- 4. Migrerar tracked_keywords.domain från subscribers.domain.
--
-- Idempotent: säker att köra igen (IF NOT EXISTS / ON CONFLICT DO NOTHING).
-- Kör i Supabase SQL Editor INNAN ny appversion deployas.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. user_domains
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS user_domains (
    id          bigserial    PRIMARY KEY,
    user_id     uuid         NOT NULL,
    domain      text         NOT NULL,
    market      text         NOT NULL DEFAULT 'br',
    is_active   boolean      NOT NULL DEFAULT true,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT user_domains_unique UNIQUE (user_id, domain)
);

CREATE INDEX IF NOT EXISTS idx_user_domains_user_active
    ON user_domains (user_id, is_active);

ALTER TABLE user_domains ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "users can access own domains" ON user_domains;
CREATE POLICY "users can access own domains"
    ON user_domains
    FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- 2. domain-kolumn på tracked_keywords (nullable first)
-- ---------------------------------------------------------------------------

ALTER TABLE tracked_keywords
    ADD COLUMN IF NOT EXISTS domain TEXT;

-- ---------------------------------------------------------------------------
-- 3. Datamigrering: subscribers.domain → user_domains
-- ---------------------------------------------------------------------------

INSERT INTO user_domains (user_id, domain, market, is_active, created_at)
SELECT
    user_id,
    domain,
    COALESCE(market, 'br'),
    true,
    COALESCE(created_at, now())
FROM subscribers
WHERE domain IS NOT NULL
  AND user_id IS NOT NULL
ON CONFLICT (user_id, domain) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Datamigrering: sätt tracked_keywords.domain = subscribers.domain
-- ---------------------------------------------------------------------------

UPDATE tracked_keywords tk
SET domain = s.domain
FROM subscribers s
WHERE tk.user_id = s.user_id
  AND s.domain IS NOT NULL
  AND tk.domain IS NULL;

-- ---------------------------------------------------------------------------
-- Verifieringsfrågor — kör efter migrering
-- ---------------------------------------------------------------------------
--
-- Kontrollera user_domains:
-- SELECT COUNT(*) FROM user_domains;
-- SELECT user_id, domain, market, is_active FROM user_domains LIMIT 10;
--
-- Kontrollera tracked_keywords.domain-kolumn:
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'tracked_keywords' AND column_name = 'domain';
-- Förväntat: is_nullable = YES (nullable tills vidare)
--
-- Kontrollera migreringsresultat:
-- SELECT COUNT(*) as total,
--        COUNT(domain) as with_domain,
--        COUNT(*) - COUNT(domain) as without_domain
-- FROM tracked_keywords WHERE is_active = true;
-- OBS: without_domain = keywords för användare utan domän — dessa hanteras
--      inte av rank_tracker förrän domänen är satt, vilket är korrekt beteende.
--
-- Nästa steg (valfritt, kör INTE förrän without_domain = 0 eller acceptabelt):
-- ALTER TABLE tracked_keywords ALTER COLUMN domain SET NOT NULL;
-- =============================================================================

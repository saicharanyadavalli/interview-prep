-- =============================================================================
-- Migration 002: RDS Identity Continuity Schema
-- Target Database: interview_prep_db
-- Schema: public
-- Maps external authentication providers (Amazon Cognito, Google OAuth)
-- to authoritative internal user_profiles (UUID) while preserving history.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  provider VARCHAR(50) NOT NULL,
  provider_sub VARCHAR(255) NOT NULL,
  email VARCHAR(255),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_provider_sub UNIQUE (provider, provider_sub)
);

-- Index on user_id for fast retrieval of linked identities
CREATE INDEX IF NOT EXISTS idx_user_identities_user_id
  ON public.user_identities(user_id);

-- Composite index on (provider, provider_sub) for fast identity lookup & resolution
CREATE INDEX IF NOT EXISTS idx_user_identities_provider_sub
  ON public.user_identities(provider, provider_sub);

-- Automatic updated_at trigger using existing function set_current_timestamp_updated_at
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_user_identities_updated_at'
  ) THEN
    CREATE TRIGGER trg_user_identities_updated_at
      BEFORE UPDATE ON public.user_identities
      FOR EACH ROW
      EXECUTE FUNCTION public.set_current_timestamp_updated_at();
  END IF;
END $$;

COMMIT;

-- =============================================================================
-- Migration 003: Custom Question Folders
-- Allows users to organize questions into named custom folders/lists
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_custom_folders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  folder_name TEXT NOT NULL,
  qnums INTEGER[] NOT NULL DEFAULT '{}'::int[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_user_folder_name UNIQUE (user_id, folder_name)
);

CREATE INDEX IF NOT EXISTS idx_user_custom_folders_user ON public.user_custom_folders(user_id);
CREATE INDEX IF NOT EXISTS idx_user_custom_folders_name ON public.user_custom_folders(folder_name);

DROP TRIGGER IF EXISTS trg_user_custom_folders_updated_at ON public.user_custom_folders;
CREATE TRIGGER trg_user_custom_folders_updated_at
  BEFORE UPDATE ON public.user_custom_folders
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

COMMIT;

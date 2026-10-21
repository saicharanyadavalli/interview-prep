-- =============================================================================
-- Migration 004: LeetCode Synchronization State and Audit History
-- Tracks upstream repository synchronization checkpoints and delivery webhook runs
-- Target Database: Amazon RDS PostgreSQL 17.11 (database: interview_prep_db)
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. LEETCODE SYNC STATE
-- Stores the latest successfully synchronized commit SHA per source repo & branch
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.leetcode_sync_state (
  source_repo TEXT NOT NULL,
  source_branch TEXT NOT NULL,
  last_sync_commit_sha TEXT NOT NULL,
  last_sync_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source_repo, source_branch)
);

-- -----------------------------------------------------------------------------
-- 2. LEETCODE SYNC HISTORY
-- Audit trail of each webhook delivery or manual sync trigger
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.leetcode_sync_history (
  delivery_id TEXT PRIMARY KEY,
  source_repo TEXT NOT NULL,
  source_branch TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('in_progress', 'success', 'failed', 'ignored')),
  files_processed INTEGER NOT NULL DEFAULT 0,
  files_added INTEGER NOT NULL DEFAULT 0,
  files_updated INTEGER NOT NULL DEFAULT 0,
  files_ignored INTEGER NOT NULL DEFAULT 0,
  files_failed INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- 3. INDEXES
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_commit ON public.leetcode_sync_history(commit_sha);
CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_created_at ON public.leetcode_sync_history(created_at);
CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_repo_branch ON public.leetcode_sync_history(source_repo, source_branch);

-- -----------------------------------------------------------------------------
-- 4. TRIGGERS
-- -----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_leetcode_sync_state_updated_at ON public.leetcode_sync_state;
CREATE TRIGGER trg_leetcode_sync_state_updated_at
  BEFORE UPDATE ON public.leetcode_sync_state
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

COMMIT;

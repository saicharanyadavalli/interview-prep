BEGIN;

-- ============================================================
-- SCHEMA + EXTENSIONS
-- ============================================================
SET search_path = public, auth, extensions;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- UTIL FUNCTIONS
-- ============================================================
CREATE OR REPLACE FUNCTION public.set_current_timestamp_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ============================================================
-- CORE TABLES
-- ============================================================

CREATE TABLE public.user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  avatar_url TEXT NOT NULL DEFAULT '',
  system_design_completed_steps INTEGER[] NOT NULL DEFAULT '{}'::int[],
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT user_profiles_system_design_steps_range_chk
    CHECK (
      system_design_completed_steps <@ ARRAY[
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
        11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24, 25, 26, 27, 28, 29, 30
      ]::int[]
    )
);

CREATE TABLE public.user_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  qnum INTEGER NOT NULL CHECK (qnum > 0),
  is_solved BOOLEAN NOT NULL DEFAULT FALSE,
  is_revisit BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, qnum)
);

CREATE TABLE public.practice_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  qnum INTEGER NOT NULL CHECK (qnum > 0),
  practiced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.user_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  qnum INTEGER NOT NULL CHECK (qnum > 0),
  comment_text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backfill from legacy user_progress rows reserved for system design (qnum 900001..900030).
-- Existing non-empty arrays are preserved to avoid overwriting newer data.
WITH solved_steps AS (
  SELECT
    up.user_id AS profile_id,
    ARRAY_AGG(DISTINCT (up.qnum - 900000) ORDER BY (up.qnum - 900000)) AS completed_steps
  FROM public.user_progress AS up
  WHERE up.is_solved = TRUE
    AND up.qnum BETWEEN 900001 AND 900030
  GROUP BY up.user_id
)
UPDATE public.user_profiles AS p
SET
  system_design_completed_steps = COALESCE(s.completed_steps, '{}'::int[]),
  updated_at = now()
FROM solved_steps AS s
WHERE p.id = s.profile_id
  AND COALESCE(array_length(p.system_design_completed_steps, 1), 0) = 0;

-- ============================================================
-- QUESTION BANK
-- ============================================================

CREATE TABLE public.question_bank_questions (
  qnum INTEGER PRIMARY KEY CHECK (qnum > 0),
  question_id TEXT NOT NULL,
  problem_name TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  problem_url TEXT NOT NULL DEFAULT '',
  statement_text TEXT NOT NULL DEFAULT '',
  constraints_text TEXT NOT NULL DEFAULT '',
  examples JSONB NOT NULL DEFAULT '[]'::jsonb,
  topic_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
  company_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  primary_company TEXT NOT NULL,
  companies TEXT[] NOT NULL DEFAULT '{}'::text[],
  company_count INTEGER NOT NULL DEFAULT 1 CHECK (company_count >= 1),
  source_qnums INTEGER[] NOT NULL DEFAULT '{}'::int[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.question_bank_qnum_aliases (
  source_qnum INTEGER PRIMARY KEY CHECK (source_qnum > 0),
  canonical_qnum INTEGER NOT NULL REFERENCES public.question_bank_questions(qnum) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TRIGGERS
-- ============================================================

CREATE TRIGGER trg_user_profiles_updated_at
BEFORE UPDATE ON public.user_profiles
FOR EACH ROW
EXECUTE FUNCTION public.set_current_timestamp_updated_at();

CREATE TRIGGER trg_user_progress_updated_at
BEFORE UPDATE ON public.user_progress
FOR EACH ROW
EXECUTE FUNCTION public.set_current_timestamp_updated_at();

CREATE TRIGGER trg_question_bank_updated_at
BEFORE UPDATE ON public.question_bank_questions
FOR EACH ROW
EXECUTE FUNCTION public.set_current_timestamp_updated_at();

-- ============================================================
-- INDEXES
-- ============================================================

-- user_progress
CREATE INDEX idx_user_progress_user ON public.user_progress(user_id);
CREATE INDEX idx_user_progress_qnum ON public.user_progress(qnum);
CREATE INDEX idx_user_progress_user_solved ON public.user_progress(user_id, is_solved);
CREATE INDEX idx_user_progress_user_revisit ON public.user_progress(user_id, is_revisit);

-- practice_history
CREATE INDEX idx_practice_history_user ON public.practice_history(user_id);
CREATE INDEX idx_practice_history_time ON public.practice_history(practiced_at DESC);

-- comments
CREATE INDEX idx_user_comments_user_qnum ON public.user_comments(user_id, qnum);

-- profiles
CREATE INDEX idx_user_profiles_email ON public.user_profiles(email);

-- question bank
CREATE INDEX idx_qb_question_id ON public.question_bank_questions(question_id);
CREATE INDEX idx_qb_name ON public.question_bank_questions(problem_name);
CREATE INDEX idx_qb_difficulty ON public.question_bank_questions(difficulty);
CREATE INDEX idx_qb_topic_tags ON public.question_bank_questions USING GIN (topic_tags);
CREATE INDEX idx_qb_company_tags ON public.question_bank_questions USING GIN (company_tags);

CREATE INDEX idx_qb_alias_canonical ON public.question_bank_qnum_aliases(canonical_qnum);

-- ============================================================
-- PRIVILEGES
-- ============================================================

GRANT USAGE ON SCHEMA public TO anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  public.user_profiles,
  public.user_progress,
  public.practice_history,
  public.user_comments
TO authenticated;

GRANT SELECT ON
  public.question_bank_questions,
  public.question_bank_qnum_aliases
TO anon, authenticated;

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.practice_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.question_bank_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.question_bank_qnum_aliases ENABLE ROW LEVEL SECURITY;

-- user_profiles
CREATE POLICY "profile_select" ON public.user_profiles
FOR SELECT USING (auth.uid() = id);

CREATE POLICY "profile_insert" ON public.user_profiles
FOR INSERT WITH CHECK (auth.uid() = id);

CREATE POLICY "profile_update" ON public.user_profiles
FOR UPDATE USING (auth.uid() = id);

-- user_progress
CREATE POLICY "progress_select" ON public.user_progress
FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "progress_insert" ON public.user_progress
FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "progress_update" ON public.user_progress
FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "progress_delete" ON public.user_progress
FOR DELETE USING (auth.uid() = user_id);

-- practice_history
CREATE POLICY "history_select" ON public.practice_history
FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "history_insert" ON public.practice_history
FOR INSERT WITH CHECK (auth.uid() = user_id);

-- comments
CREATE POLICY "comments_all" ON public.user_comments
FOR ALL USING (auth.uid() = user_id);

-- public read (question bank)
CREATE POLICY "qb_read" ON public.question_bank_questions
FOR SELECT USING (true);

CREATE POLICY "qb_alias_read" ON public.question_bank_qnum_aliases
FOR SELECT USING (true);

COMMIT;
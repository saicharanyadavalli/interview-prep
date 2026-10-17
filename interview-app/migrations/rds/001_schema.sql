-- =============================================================================
-- AWS RDS PostgreSQL 17.11 Canonical Schema Definition
-- Target Database: interview_prep_db
-- Schema: public
-- Decoupled from Supabase-specific auth.users and internal extensions.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. EXTENSIONS
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 2. UTILITY FUNCTIONS
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_current_timestamp_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- 3. CORE APPLICATION USER ENTITY
-- -----------------------------------------------------------------------------
-- Serves as the authoritative user entity in Amazon RDS.
-- Decoupled from Supabase internal auth schema.
CREATE TABLE IF NOT EXISTS public.user_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  username TEXT UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  avatar_url TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 4. QUESTION BANK (INTERVIEW PROBLEMS & ALIASES)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.question_bank_questions (
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
  primary_company TEXT NOT NULL DEFAULT '',
  companies TEXT[] NOT NULL DEFAULT '{}'::text[],
  company_count INTEGER NOT NULL DEFAULT 1 CHECK (company_count >= 1),
  source_qnums INTEGER[] NOT NULL DEFAULT '{}'::int[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_question_bank_questions_question_id UNIQUE (question_id)
);

CREATE TABLE IF NOT EXISTS public.question_bank_qnum_aliases (
  source_qnum INTEGER PRIMARY KEY CHECK (source_qnum > 0),
  canonical_qnum INTEGER NOT NULL REFERENCES public.question_bank_questions(qnum) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 5. LEETCODE DSA MASTER TABLES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.leetcode_problems (
  qnum INTEGER PRIMARY KEY CHECK (qnum > 0),
  title TEXT NOT NULL,
  slug TEXT NOT NULL,
  difficulty TEXT NOT NULL CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
  rating NUMERIC DEFAULT NULL,
  topic_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
  company_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
  description_md TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_leetcode_problems_slug UNIQUE (slug)
);

CREATE TABLE IF NOT EXISTS public.leetcode_approaches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  qnum INTEGER NOT NULL REFERENCES public.leetcode_problems(qnum) ON DELETE CASCADE,
  approach_index INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL DEFAULT 'Solution Approach',
  intuition_md TEXT NOT NULL DEFAULT '',
  time_complexity TEXT NOT NULL DEFAULT '',
  space_complexity TEXT NOT NULL DEFAULT '',
  explanation_md TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_leetcode_approaches_qnum_idx UNIQUE (qnum, approach_index)
);

CREATE TABLE IF NOT EXISTS public.leetcode_code_solutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  qnum INTEGER NOT NULL REFERENCES public.leetcode_problems(qnum) ON DELETE CASCADE,
  language TEXT NOT NULL,
  code_content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_leetcode_code_solutions_qnum_lang UNIQUE (qnum, language)
);

-- -----------------------------------------------------------------------------
-- 6. SYSTEM DESIGN & LEARNING TRACK LESSONS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.course_lessons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id TEXT NOT NULL,
  step_no INTEGER NOT NULL CHECK (step_no > 0),
  title TEXT NOT NULL,
  html_content TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_course_lessons_track_step UNIQUE (track_id, step_no)
);

-- -----------------------------------------------------------------------------
-- 7. USER PROGRESS, HISTORY, COMMENTS & TRACK COMPLETION
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  qnum INTEGER NOT NULL CHECK (qnum > 0),
  is_solved BOOLEAN NOT NULL DEFAULT FALSE,
  is_revisit BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_user_progress_user_qnum UNIQUE (user_id, qnum)
);

CREATE TABLE IF NOT EXISTS public.practice_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  qnum INTEGER NOT NULL CHECK (qnum > 0),
  practiced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.user_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  qnum INTEGER NOT NULL CHECK (qnum > 0),
  comment_text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.learning_track_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  track_id TEXT NOT NULL,
  step_no INTEGER NOT NULL CHECK (step_no > 0),
  completed BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_learning_track_progress_user_track_step UNIQUE (user_id, track_id, step_no)
);

-- -----------------------------------------------------------------------------
-- 8. INDEXES
-- -----------------------------------------------------------------------------

-- user_profiles
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON public.user_profiles(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_username ON public.user_profiles(username);

-- question_bank_questions
CREATE INDEX IF NOT EXISTS idx_qb_question_id ON public.question_bank_questions(question_id);
CREATE INDEX IF NOT EXISTS idx_qb_name ON public.question_bank_questions(problem_name);
CREATE INDEX IF NOT EXISTS idx_qb_difficulty ON public.question_bank_questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_qb_topic_tags ON public.question_bank_questions USING GIN (topic_tags);
CREATE INDEX IF NOT EXISTS idx_qb_company_tags ON public.question_bank_questions USING GIN (company_tags);

-- question_bank_qnum_aliases
CREATE INDEX IF NOT EXISTS idx_qb_alias_canonical ON public.question_bank_qnum_aliases(canonical_qnum);

-- leetcode_problems
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_slug ON public.leetcode_problems(slug);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_difficulty ON public.leetcode_problems(difficulty);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_rating ON public.leetcode_problems(rating DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_topic_tags ON public.leetcode_problems USING GIN (topic_tags);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_company_tags ON public.leetcode_problems USING GIN (company_tags);

-- leetcode_approaches & solutions
CREATE INDEX IF NOT EXISTS idx_leetcode_approaches_qnum ON public.leetcode_approaches(qnum);
CREATE INDEX IF NOT EXISTS idx_leetcode_code_solutions_qnum_lang ON public.leetcode_code_solutions(qnum, language);

-- course_lessons
CREATE INDEX IF NOT EXISTS idx_course_lessons_track_step ON public.course_lessons(track_id, step_no);

-- user_progress
CREATE INDEX IF NOT EXISTS idx_user_progress_user ON public.user_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_qnum ON public.user_progress(qnum);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_solved ON public.user_progress(user_id, is_solved);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_revisit ON public.user_progress(user_id, is_revisit);

-- practice_history
CREATE INDEX IF NOT EXISTS idx_practice_history_user ON public.practice_history(user_id);
CREATE INDEX IF NOT EXISTS idx_practice_history_time ON public.practice_history(practiced_at DESC);

-- user_comments
CREATE INDEX IF NOT EXISTS idx_user_comments_user_qnum ON public.user_comments(user_id, qnum);

-- learning_track_progress
CREATE INDEX IF NOT EXISTS idx_learning_track_progress_user_track ON public.learning_track_progress(user_id, track_id);

-- -----------------------------------------------------------------------------
-- 9. TRIGGERS (AUTOMATIC updated_at SYNCHRONIZATION)
-- -----------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_user_profiles_updated_at ON public.user_profiles;
CREATE TRIGGER trg_user_profiles_updated_at
  BEFORE UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS trg_question_bank_updated_at ON public.question_bank_questions;
CREATE TRIGGER trg_question_bank_updated_at
  BEFORE UPDATE ON public.question_bank_questions
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS trg_leetcode_problems_updated_at ON public.leetcode_problems;
CREATE TRIGGER trg_leetcode_problems_updated_at
  BEFORE UPDATE ON public.leetcode_problems
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS trg_user_progress_updated_at ON public.user_progress;
CREATE TRIGGER trg_user_progress_updated_at
  BEFORE UPDATE ON public.user_progress
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS trg_learning_track_progress_updated_at ON public.learning_track_progress;
CREATE TRIGGER trg_learning_track_progress_updated_at
  BEFORE UPDATE ON public.learning_track_progress
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

COMMIT;

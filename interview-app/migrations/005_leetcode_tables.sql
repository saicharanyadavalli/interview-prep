BEGIN;

-- ============================================================
-- LEETCODE DSA EXCLUSIVE TABLES (Option A)
-- ============================================================

-- 1. Master LeetCode Problems Table
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
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Solution Approaches Table
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

-- 3. Code Solutions Table (Multi-Language)
CREATE TABLE IF NOT EXISTS public.leetcode_code_solutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  qnum INTEGER NOT NULL REFERENCES public.leetcode_problems(qnum) ON DELETE CASCADE,
  language TEXT NOT NULL,
  code_content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_leetcode_code_solutions_qnum_lang UNIQUE (qnum, language)
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_slug ON public.leetcode_problems(slug);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_difficulty ON public.leetcode_problems(difficulty);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_rating ON public.leetcode_problems(rating DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_leetcode_problems_topic_tags ON public.leetcode_problems USING GIN (topic_tags);
CREATE INDEX IF NOT EXISTS idx_leetcode_approaches_qnum ON public.leetcode_approaches(qnum);
CREATE INDEX IF NOT EXISTS idx_leetcode_code_solutions_qnum_lang ON public.leetcode_code_solutions(qnum, language);

-- ============================================================
-- ROW LEVEL SECURITY (RLS) & PRIVILEGES
-- ============================================================
ALTER TABLE public.leetcode_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leetcode_approaches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leetcode_code_solutions ENABLE ROW LEVEL SECURITY;

GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT ON public.leetcode_problems, public.leetcode_approaches, public.leetcode_code_solutions TO anon, authenticated;
GRANT ALL ON public.leetcode_problems, public.leetcode_approaches, public.leetcode_code_solutions TO service_role;

DROP POLICY IF EXISTS "Allow public read on leetcode_problems" ON public.leetcode_problems;
CREATE POLICY "Allow public read on leetcode_problems" ON public.leetcode_problems FOR SELECT USING (true);

DROP POLICY IF EXISTS "Allow public read on leetcode_approaches" ON public.leetcode_approaches;
CREATE POLICY "Allow public read on leetcode_approaches" ON public.leetcode_approaches FOR SELECT USING (true);

DROP POLICY IF EXISTS "Allow public read on leetcode_code_solutions" ON public.leetcode_code_solutions;
CREATE POLICY "Allow public read on leetcode_code_solutions" ON public.leetcode_code_solutions FOR SELECT USING (true);

COMMIT;

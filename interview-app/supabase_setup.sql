-- ============================================================
-- Interview Practice Platform -- Supabase Database Setup
-- Run this entire script in the Supabase SQL Editor
-- ============================================================

-- 1. User Progress Table (lean: only user_id + qnum + status)
CREATE TABLE IF NOT EXISTS user_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  qnum INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('strong', 'good', 'revisit', 'skip')),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, qnum)
);

-- Progress model v2: separate solved/unsolved outcome from revisit flag.
ALTER TABLE user_progress
  ADD COLUMN IF NOT EXISTS outcome TEXT CHECK (outcome IN ('solved', 'unsolved'));

ALTER TABLE user_progress
  ADD COLUMN IF NOT EXISTS is_revisit BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE user_progress
SET outcome = CASE
  WHEN status IN ('good', 'strong') THEN 'solved'
  ELSE 'unsolved'
END
WHERE outcome IS NULL;

UPDATE user_progress
SET is_revisit = TRUE
WHERE status = 'revisit' AND is_revisit = FALSE;

-- 2. Practice History Table (lean: only user_id + qnum)
CREATE TABLE IF NOT EXISTS practice_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  qnum INTEGER NOT NULL,
  practiced_at TIMESTAMPTZ DEFAULT now()
);

-- 3. User Comments Table (lean: user_id + qnum + comment)
CREATE TABLE IF NOT EXISTS user_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  qnum INTEGER NOT NULL,
  comment_text TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. User Profile Table (editable profile fields)
CREATE TABLE IF NOT EXISTS user_profiles (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  avatar_url TEXT DEFAULT '',
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Row Level Security
-- ============================================================
ALTER TABLE user_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- user_progress policies
DROP POLICY IF EXISTS "Users can view own progress" ON user_progress;
CREATE POLICY "Users can view own progress"
  ON user_progress FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can insert own progress" ON user_progress;
CREATE POLICY "Users can insert own progress"
  ON user_progress FOR INSERT WITH CHECK (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can update own progress" ON user_progress;
CREATE POLICY "Users can update own progress"
  ON user_progress FOR UPDATE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can delete own progress" ON user_progress;
CREATE POLICY "Users can delete own progress"
  ON user_progress FOR DELETE USING (auth.uid() = user_id);

-- practice_history policies
DROP POLICY IF EXISTS "Users can view own history" ON practice_history;
CREATE POLICY "Users can view own history"
  ON practice_history FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can insert own history" ON practice_history;
CREATE POLICY "Users can insert own history"
  ON practice_history FOR INSERT WITH CHECK (auth.uid() = user_id);

-- user_comments policies
DROP POLICY IF EXISTS "Users can view own comments" ON user_comments;
CREATE POLICY "Users can view own comments"
  ON user_comments FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can insert own comments" ON user_comments;
CREATE POLICY "Users can insert own comments"
  ON user_comments FOR INSERT WITH CHECK (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can delete own comments" ON user_comments;
CREATE POLICY "Users can delete own comments"
  ON user_comments FOR DELETE USING (auth.uid() = user_id);

-- user_profiles policies
DROP POLICY IF EXISTS "Users can view own profile" ON user_profiles;
CREATE POLICY "Users can view own profile"
  ON user_profiles FOR SELECT USING (auth.uid() = id);
DROP POLICY IF EXISTS "Users can insert own profile" ON user_profiles;
CREATE POLICY "Users can insert own profile"
  ON user_profiles FOR INSERT WITH CHECK (auth.uid() = id);
DROP POLICY IF EXISTS "Users can update own profile" ON user_profiles;
CREATE POLICY "Users can update own profile"
  ON user_profiles FOR UPDATE USING (auth.uid() = id);

-- ============================================================
-- Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_user_progress_user ON user_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_qnum ON user_progress(qnum);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_revisit ON user_progress(user_id, is_revisit);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_outcome ON user_progress(user_id, outcome);
CREATE INDEX IF NOT EXISTS idx_practice_history_user ON practice_history(user_id);
CREATE INDEX IF NOT EXISTS idx_practice_history_time ON practice_history(practiced_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_comments_user_qnum ON user_comments(user_id, qnum);
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);

-- ============================================================
-- Service role bypass (for backend with service_role key)
-- ============================================================
DROP POLICY IF EXISTS "Service role full access to user_progress" ON user_progress;
CREATE POLICY "Service role full access to user_progress"
  ON user_progress FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "Service role full access to practice_history" ON practice_history;
CREATE POLICY "Service role full access to practice_history"
  ON practice_history FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "Service role full access to user_comments" ON user_comments;
CREATE POLICY "Service role full access to user_comments"
  ON user_comments FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "Service role full access to user_profiles" ON user_profiles;
CREATE POLICY "Service role full access to user_profiles"
  ON user_profiles FOR ALL USING (auth.role() = 'service_role');

-- ============================================================
-- Question Bank Tables (DB-native question catalog)
-- ============================================================
CREATE TABLE IF NOT EXISTS question_bank_questions (
  qnum INTEGER PRIMARY KEY,
  question_id TEXT NOT NULL,
  problem_name TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  problem_url TEXT DEFAULT '',
  statement_text TEXT DEFAULT '',
  constraints_text TEXT DEFAULT '',
  examples JSONB NOT NULL DEFAULT '[]'::jsonb,
  topic_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
  company_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  primary_company TEXT NOT NULL,
  companies TEXT[] NOT NULL DEFAULT '{}'::text[],
  company_count INTEGER NOT NULL DEFAULT 1,
  source_qnums INTEGER[] NOT NULL DEFAULT '{}'::int[],
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE question_bank_questions
  ADD COLUMN IF NOT EXISTS source_qnums INTEGER[] NOT NULL DEFAULT '{}'::int[];

CREATE TABLE IF NOT EXISTS question_bank_companies (
  qnum INTEGER NOT NULL REFERENCES question_bank_questions(qnum) ON DELETE CASCADE,
  company TEXT NOT NULL,
  difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (qnum, company, difficulty)
);

CREATE TABLE IF NOT EXISTS question_bank_qnum_aliases (
  source_qnum INTEGER PRIMARY KEY,
  canonical_qnum INTEGER NOT NULL REFERENCES question_bank_questions(qnum) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_question_bank_questions_question_id ON question_bank_questions(question_id);
CREATE INDEX IF NOT EXISTS idx_question_bank_questions_name ON question_bank_questions(problem_name);
CREATE INDEX IF NOT EXISTS idx_question_bank_questions_difficulty ON question_bank_questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_question_bank_companies_company_diff ON question_bank_companies(company, difficulty);
CREATE INDEX IF NOT EXISTS idx_question_bank_companies_qnum ON question_bank_companies(qnum);
CREATE INDEX IF NOT EXISTS idx_question_bank_qnum_aliases_canonical ON question_bank_qnum_aliases(canonical_qnum);

ALTER TABLE question_bank_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE question_bank_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE question_bank_qnum_aliases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read question bank questions" ON question_bank_questions;
CREATE POLICY "Public read question bank questions"
  ON question_bank_questions FOR SELECT USING (true);
DROP POLICY IF EXISTS "Public read question bank companies" ON question_bank_companies;
CREATE POLICY "Public read question bank companies"
  ON question_bank_companies FOR SELECT USING (true);
DROP POLICY IF EXISTS "Public read question bank qnum aliases" ON question_bank_qnum_aliases;
CREATE POLICY "Public read question bank qnum aliases"
  ON question_bank_qnum_aliases FOR SELECT USING (true);

DROP POLICY IF EXISTS "Service role full access to question_bank_questions" ON question_bank_questions;
CREATE POLICY "Service role full access to question_bank_questions"
  ON question_bank_questions FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "Service role full access to question_bank_companies" ON question_bank_companies;
CREATE POLICY "Service role full access to question_bank_companies"
  ON question_bank_companies FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "Service role full access to question_bank_qnum_aliases" ON question_bank_qnum_aliases;
CREATE POLICY "Service role full access to question_bank_qnum_aliases"
  ON question_bank_qnum_aliases FOR ALL USING (auth.role() = 'service_role');

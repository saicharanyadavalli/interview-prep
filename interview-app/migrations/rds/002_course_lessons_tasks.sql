-- -----------------------------------------------------------------------------
-- Migration 002: Add tasks JSONB and slug columns to course_lessons
-- Authoritative schema update for Amazon RDS PostgreSQL
-- -----------------------------------------------------------------------------

-- 1. Add tasks column with empty JSON array default if not present
ALTER TABLE public.course_lessons
  ADD COLUMN IF NOT EXISTS tasks JSONB NOT NULL DEFAULT '[]'::jsonb;

-- 2. Add slug column for SEO and human-readable lesson routing
ALTER TABLE public.course_lessons
  ADD COLUMN IF NOT EXISTS slug TEXT;

-- 3. Add index on track_id and slug for fast lesson detail lookup
CREATE INDEX IF NOT EXISTS idx_course_lessons_track_slug
  ON public.course_lessons(track_id, slug);

-- 4. Add index on tasks JSONB for querying lessons with tasks
CREATE INDEX IF NOT EXISTS idx_course_lessons_tasks
  ON public.course_lessons USING GIN (tasks);

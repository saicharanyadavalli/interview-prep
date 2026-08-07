-- ============================================================
-- Migration 008: Add missing RLS DELETE/UPDATE policies
-- Adds defensive policies for tables that were missing them.
-- Run this in Supabase SQL Editor.
-- ============================================================

BEGIN;

-- 1. user_profiles: add DELETE policy (users can delete own profile)
DO $$ BEGIN
  CREATE POLICY "profile_delete" ON public.user_profiles
    FOR DELETE USING (auth.uid() = id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 2. practice_history: add DELETE policy (users can delete own history)
DO $$ BEGIN
  CREATE POLICY "history_delete" ON public.practice_history
    FOR DELETE USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 3. practice_history: add UPDATE policy (users can update own history)
DO $$ BEGIN
  CREATE POLICY "history_update" ON public.practice_history
    FOR UPDATE USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMIT;

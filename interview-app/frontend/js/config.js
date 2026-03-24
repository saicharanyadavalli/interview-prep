/**
 * config.js — Centralized configuration for the Interview Practice Platform.
 *
 * For local development the backend runs on http://localhost:8000.
 * For production, change API_BASE_URL to your deployed backend URL.
 *
 * SUPABASE_URL and SUPABASE_ANON_KEY must match the values from your
 * Supabase project dashboard (Settings → API).
 */

const CONFIG = {
  // Backend API base URL (no trailing slash)
  API_BASE_URL: "http://localhost:8000",

  // Supabase project credentials (public / anon key — safe for frontend)
  SUPABASE_URL: "https://armfnjzilchguppytyvm.supabase.co",
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFybWZuanppbGNoZ3VwcHl0eXZtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3NzY2MzgsImV4cCI6MjA4OTM1MjYzOH0.W7Q-MN00eeaIQZEHfkagMVX592nu8D6yGsh9e_uHctc",
};

import { createBrowserClient } from '@supabase/ssr'
import { SupabaseClient } from "@supabase/supabase-js";
import { CONFIG } from "./config";

let supabaseInstance: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (supabaseInstance) return supabaseInstance;
  if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
    console.error("Supabase environment variables missing.");
    return null;
  }
  supabaseInstance = createBrowserClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
  return supabaseInstance;
}

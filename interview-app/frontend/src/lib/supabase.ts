import { createBrowserClient } from '@supabase/ssr'
import { SupabaseClient } from "@supabase/supabase-js";
import { CONFIG } from "./config";

let supabaseInstance: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (supabaseInstance) return supabaseInstance;
  const supabaseUrl = (CONFIG.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim().replace(/^["']|["']$/g, "");
  const supabaseAnonKey = (CONFIG.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim().replace(/^["']|["']$/g, "");

  if (!supabaseUrl || !supabaseAnonKey) {
    console.error("Supabase environment variables missing.");
    return null;
  }
  supabaseInstance = createBrowserClient(supabaseUrl, supabaseAnonKey);
  return supabaseInstance;
}

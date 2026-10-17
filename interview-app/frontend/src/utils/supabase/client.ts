import { createBrowserClient } from '@supabase/ssr';
import { CONFIG } from '@/lib/config';

export function createClient() {
  const supabaseUrl = (CONFIG.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim().replace(/^["']|["']$/g, "");
  const supabaseAnonKey = (CONFIG.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim().replace(/^["']|["']$/g, "");

  return createBrowserClient(
    supabaseUrl,
    supabaseAnonKey
  );
}

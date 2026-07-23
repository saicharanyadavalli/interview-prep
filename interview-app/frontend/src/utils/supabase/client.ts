import { createBrowserClient } from '@supabase/ssr';
import { CONFIG } from '@/lib/config';

export function createClient() {
  return createBrowserClient(
    CONFIG.SUPABASE_URL,
    CONFIG.SUPABASE_ANON_KEY
  );
}

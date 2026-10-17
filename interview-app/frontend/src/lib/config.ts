function cleanEnv(val: string | undefined): string {
  if (!val) return "";
  return val.trim().replace(/^["']|["']$/g, "");
}

export const CONFIG = {
  API_BASE_URL: cleanEnv(process.env.NEXT_PUBLIC_API_BASE_URL) || "/api/backend",
  SUPABASE_URL: cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL),
  SUPABASE_ANON_KEY: cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY),
};

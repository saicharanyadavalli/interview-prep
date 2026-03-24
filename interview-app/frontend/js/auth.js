/**
 * auth.js — Supabase authentication helper.
 *
 * Uses the Supabase JS client loaded from CDN (included in each HTML page).
 * Provides login, logout, session checking, and route guarding.
 */

// Supabase client singleton (initialized once)
let _supabase = null;

function getSupabase() {
  if (_supabase) return _supabase;
  if (typeof CONFIG === "undefined") {
    console.error("CONFIG not loaded. Include config.js before auth.js");
    return null;
  }
  // supabase-js is loaded from CDN and exposes window.supabase
  _supabase = supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
  return _supabase;
}

/**
 * Sign in with Google via Supabase OAuth.
 * Redirects the browser to Google's consent screen.
 */
async function signInWithGoogle() {
  const sb = getSupabase();
  if (!sb) return;

  const { error } = await sb.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: window.location.origin + "/dashboard.html",
    },
  });

  if (error) {
    console.error("Sign-in error:", error.message);
    alert("Sign-in failed: " + error.message);
  }
}

/**
 * Sign out the current user and redirect to login.
 */
async function signOut() {
  const sb = getSupabase();
  if (!sb) return;

  await sb.auth.signOut();
  try {
    localStorage.removeItem("ipp_profile_cache_v1");
  } catch (_) {
    // Ignore storage errors.
  }
  window.location.href = "login.html";
}

/**
 * Get the current session. Returns { session, user } or nulls.
 */
async function getSession() {
  const sb = getSupabase();
  if (!sb) return { session: null, user: null };

  const { data } = await sb.auth.getSession();
  const session = data?.session || null;
  const user = session?.user || null;
  return { session, user };
}

/**
 * Get the current access token (JWT) for backend API calls.
 */
async function getAccessToken() {
  const { session } = await getSession();
  return session?.access_token || null;
}

/**
 * Route guard — redirect to login.html if user is not authenticated.
 * Call this at the top of every protected page.
 * Returns the user object if authenticated.
 */
async function requireAuth() {
  const { session, user } = await getSession();
  if (!session || !user) {
    window.location.href = "login.html";
    return null;
  }
  return user;
}

/**
 * Get user metadata (name, avatar, email) from the Supabase user object.
 */
function getUserMeta(user) {
  if (!user) return { name: "User", email: "", avatar: "" };
  const meta = user.user_metadata || {};
  return {
    name: meta.full_name || meta.name || user.email?.split("@")[0] || "User",
    email: user.email || "",
    avatar: meta.avatar_url || meta.picture || "",
  };
}

/**
 * Soft auth — returns user if logged in, or null if not.
 * Does NOT redirect. Use this for pages that work with or without auth.
 */
async function tryGetUser() {
  const { session, user } = await getSession();
  return user || null;
}

/**
 * Quick check if user is logged in.
 */
async function isLoggedIn() {
  const { session } = await getSession();
  return Boolean(session);
}

/**
 * Notify the backend about the current session (upserts user row).
 */
async function syncSessionWithBackend(accessToken) {
  if (!accessToken) return;
  try {
    await fetch(CONFIG.API_BASE_URL + "/auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: accessToken }),
    });
  } catch (_) {
    // Non-blocking sync failure; UI auth still relies on Supabase session.
  }
}

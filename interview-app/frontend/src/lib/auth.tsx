"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { getSupabase } from "./supabase";
import { User, Session } from "@supabase/supabase-js";
import { useRouter, usePathname } from "next/navigation";

import { CONFIG } from "./config";

interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  signInWithEmailOrUsername: (identifier: string, password: string) => Promise<{ error: string | null }>;
  signUpWithEmail: (email: string, password: string, username: string, fullName: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
  getUserMeta: () => { name: string; email: string; avatar: string; username: string };
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const PROTECTED_ROUTES = [
  "/dashboard",
  "/practice",
  "/questions",
  "/solve",
  "/profile",
  "/progress",
  "/revisit"
];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const sb = getSupabase();
    if (!sb) {
      setLoading(false);
      return;
    }

    if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
      setSession({ access_token: "mock-token", token_type: "bearer", user: { id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com" } } as any);
      setUser({ id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com", user_metadata: { full_name: "Test User", username: "testuser" } } as any);
      setLoading(false);
      return;
    }

    sb.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    const { data: { subscription } } = sb.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!loading) {
      if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
        if (pathname === "/login") {
          router.replace("/dashboard");
        }
        return;
      }

      const isProtected = PROTECTED_ROUTES.some(route => pathname?.startsWith(route));
      if (!user && isProtected) {
        router.replace("/login");
      } else if (user && pathname === "/login") {
        router.replace("/dashboard");
      }
    }
  }, [user, loading, pathname, router]);

  const syncBackendSession = async (accessToken: string) => {
    try {
      const apiBase = CONFIG.API_BASE_URL;
      await fetch(`${apiBase}/auth/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access_token: accessToken }),
      });
    } catch (e) {
      console.warn("Backend session sync warning:", e);
    }
  };

  const signInWithGoogle = async () => {
    if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
      setSession({ access_token: "mock-token", token_type: "bearer", user: { id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com" } } as any);
      setUser({ id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com", user_metadata: { full_name: "Test User", username: "testuser" } } as any);
      router.push("/dashboard");
      return;
    }

    const sb = getSupabase();
    if (!sb) {
      alert("Authentication is not configured. Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY environment variables.");
      return;
    }

    try {
      const redirectUrl = `${window.location.origin}/auth/callback?next=/dashboard`;
      const { data, error } = await sb.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: redirectUrl,
          queryParams: {
            access_type: 'offline',
            prompt: 'consent',
          },
        },
      });

      if (error) {
        console.error("Sign-in error:", error.message);
        alert("Sign-in failed: " + error.message);
      } else if (data?.url) {
        window.location.href = data.url;
      }
    } catch (err: any) {
      console.error("Unexpected sign-in error:", err);
      alert("An unexpected error occurred during sign-in: " + (err.message || String(err)));
    }
  };

  const signInWithEmailOrUsername = async (identifier: string, password: string): Promise<{ error: string | null }> => {
    if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
      setSession({ access_token: "mock-token", token_type: "bearer", user: { id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com" } } as any);
      setUser({ id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com", user_metadata: { full_name: "Test User", username: "testuser" } } as any);
      router.push("/dashboard");
      return { error: null };
    }

    const sb = getSupabase();
    if (!sb) {
      return { error: "Authentication client is not configured." };
    }

    let emailToUse = identifier.trim();

    // If identifier doesn't look like an email, try resolving it as a username
    if (!emailToUse.includes("@")) {
      try {
        // Strategy 1: Supabase RPC (bypasses RLS securely for anon user)
        const { data: rpcData, error: rpcError } = await sb.rpc("get_email_by_username", { p_username: emailToUse });
        if (!rpcError && rpcData) {
          const resolved = Array.isArray(rpcData) ? rpcData[0]?.email : rpcData;
          if (resolved) {
            emailToUse = resolved;
          }
        }

        // Strategy 2: Backend API fallback if RPC didn't resolve
        if (!emailToUse.includes("@")) {
          const apiBase = CONFIG.API_BASE_URL;
          const res = await fetch(`${apiBase}/auth/resolve-username`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: emailToUse }),
          });
          if (res.ok) {
            const data = await res.json();
            if (data && data.exists && data.email) {
              emailToUse = data.email;
            }
          }
        }

        if (!emailToUse.includes("@")) {
          return { error: `No user found with username "${identifier}".` };
        }
      } catch (err) {
        return { error: `Could not resolve username "${identifier}".` };
      }
    }

    try {
      const { data, error } = await sb.auth.signInWithPassword({
        email: emailToUse,
        password,
      });

      if (error) {
        return { error: error.message };
      }

      if (data.session) {
        await syncBackendSession(data.session.access_token);
        router.push("/dashboard");
      }

      return { error: null };
    } catch (err: any) {
      return { error: err.message || "An unexpected login error occurred." };
    }
  };

  const signUpWithEmail = async (
    email: string,
    password: string,
    username: string,
    fullName: string
  ): Promise<{ error: string | null }> => {
    if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
      setSession({ access_token: "mock-token", token_type: "bearer", user: { id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email } } as any);
      setUser({ id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email, user_metadata: { full_name: fullName, username } } as any);
      router.push("/dashboard");
      return { error: null };
    }

    const sb = getSupabase();
    if (!sb) {
      return { error: "Authentication client is not configured." };
    }

    const cleanEmail = email.trim().toLowerCase();
    const cleanUsername = username.trim().toLowerCase();

    // Check if username is already taken via RPC (bypasses RLS)
    try {
      const { data: rpcEmail } = await sb.rpc("get_email_by_username", { p_username: cleanUsername });
      if (rpcEmail) {
        return { error: `Username "${username}" is already taken. Please choose another username.` };
      }
    } catch (_) {}

    try {
      const { data, error } = await sb.auth.signUp({
        email: cleanEmail,
        password,
        options: {
          data: {
            full_name: fullName.trim(),
            username: cleanUsername,
          },
        },
      });

      if (error) {
        if (error.message.toLowerCase().includes("already registered") || error.message.toLowerCase().includes("already exists")) {
          return { error: `An account with email "${email}" already exists. Please sign in instead.` };
        }
        return { error: error.message };
      }

      // If user object returned with empty identities, the email is already registered
      if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
        return { error: `An account with email "${email}" already exists (e.g. registered via Google or Email). Please sign in instead.` };
      }

      if (data.session) {
        await syncBackendSession(data.session.access_token);
        router.push("/dashboard");
      } else if (data.user) {
        // Log in directly
        const loginRes = await sb.auth.signInWithPassword({
          email: cleanEmail,
          password,
        });
        if (loginRes.data?.session) {
          await syncBackendSession(loginRes.data.session.access_token);
          router.push("/dashboard");
        }
      }

      return { error: null };
    } catch (err: any) {
      return { error: err.message || "An unexpected registration error occurred." };
    }
  };

  const signOut = async () => {
    const sb = getSupabase();
    if (!sb) return;
    await sb.auth.signOut();
    try {
      localStorage.removeItem("ipp_profile_cache_v1");
    } catch (_) {}
    router.push("/login");
  };

  const getUserMeta = () => {
    if (!user) return { name: "User", email: "", avatar: "", username: "" };
    const meta = user.user_metadata || {};
    return {
      name: meta.full_name || meta.name || user.email?.split("@")[0] || "User",
      email: user.email || "",
      avatar: meta.avatar_url || meta.picture || "",
      username: meta.username || "",
    };
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        loading,
        signInWithGoogle,
        signInWithEmailOrUsername,
        signUpWithEmail,
        signOut,
        getUserMeta,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

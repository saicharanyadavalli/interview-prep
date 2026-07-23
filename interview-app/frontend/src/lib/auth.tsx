"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { getSupabase } from "./supabase";
import { User, Session } from "@supabase/supabase-js";
import { useRouter, usePathname } from "next/navigation";

import { CONFIG } from "./config";
import { API } from "./api";
import { login, signup, logout } from "@/app/actions/auth";

interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (identifier: string, password: string) => Promise<{ error: string | null }>;
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

export function AuthProvider({ 
  children,
  initialSession = null
}: { 
  children: React.ReactNode,
  initialSession?: Session | null
}) {
  const [session, setSession] = useState<Session | null>(initialSession);
  const user = session?.user ?? null;
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    setSession(initialSession);
  }, [initialSession]);



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
      setSession({ access_token: "mock-token", token_type: "bearer", user: { id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com", user_metadata: { full_name: "Test User", username: "testuser" } } } as any);
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

  const signInWithEmail = async (identifier: string, password: string): Promise<{ error: string | null }> => {
    let emailToUse = identifier.trim();

    if (!emailToUse.includes("@")) {
      return { error: `Please enter a valid email address to sign in.` };
    }

    const formData = new FormData();
    formData.append("email", emailToUse);
    formData.append("password", password);

    const result = await login(formData);

    if (result.error) {
      return { error: result.error };
    }

    window.location.href = "/dashboard";
    return { error: null };
  };



  const signUpWithEmail = async (
    email: string,
    password: string,
    username: string,
    fullName: string
  ): Promise<{ error: string | null }> => {
    const formData = new FormData();
    formData.append("email", email);
    formData.append("password", password);
    formData.append("username", username);
    formData.append("fullName", fullName);

    const result = await signup(formData);

    if (result.error) {
      return { error: result.error };
    }

    window.location.href = "/dashboard";
    return { error: null };
  };



  const signOut = async () => {
    try {
      await logout();
      localStorage.removeItem("ipp_profile_cache_v1");
    } catch (_) {}
    window.location.href = "/login";
  };

  const getUserMeta = () => {
    if (!user) return { name: "User", email: "", avatar: "", username: "" };
    const meta = user.user_metadata || {};
    let cached: any = null;
    try {
      if (typeof window !== "undefined" && API && typeof API.getCachedProfile === "function") {
        cached = API.getCachedProfile(24 * 60 * 60 * 1000);
      }
    } catch (_) {}

    const username = cached?.username || meta.username || (user.email ? user.email.split("@")[0] : "");
    const name = cached?.name || meta.full_name || meta.name || (user.email ? user.email.split("@")[0] : "User");
    const avatar = cached?.avatar_url || meta.avatar_url || meta.picture || "";

    return {
      name,
      email: user.email || "",
      avatar,
      username,
    };
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        loading,
        signInWithGoogle,
        signInWithEmail,
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

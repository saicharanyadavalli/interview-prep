"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { getSupabase } from "./supabase";
import { User, Session } from "@supabase/supabase-js";
import { useRouter, usePathname } from "next/navigation";

interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  getUserMeta: () => { name: string; email: string; avatar: string };
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
      setUser({ id: "74c4b71d-86f3-475f-aa66-9faa76ee659d", email: "testuser@example.com", user_metadata: { full_name: "Test User" } } as any);
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

  const signInWithGoogle = async () => {
    const sb = getSupabase();
    if (!sb) return;
    const { error } = await sb.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: window.location.origin + "/auth/callback?next=/dashboard",
      },
    });
    if (error) {
      console.error("Sign-in error:", error.message);
      alert("Sign-in failed: " + error.message);
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
    if (!user) return { name: "User", email: "", avatar: "" };
    const meta = user.user_metadata || {};
    return {
      name: meta.full_name || meta.name || user.email?.split("@")[0] || "User",
      email: user.email || "",
      avatar: meta.avatar_url || meta.picture || "",
    };
  };

  return (
    <AuthContext.Provider value={{ user, session, loading, signInWithGoogle, signOut, getUserMeta }}>
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

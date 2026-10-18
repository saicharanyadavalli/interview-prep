"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

import { API } from "./api";
import {
  login,
  signup,
  logout,
  initiateCognitoGoogleAuth,
  getCurrentSession,
  confirmEmail as serverConfirmEmail,
  resendVerificationCode as serverResendVerificationCode,
  requestPasswordReset as serverRequestPasswordReset,
  confirmPasswordReset as serverConfirmPasswordReset,
} from "@/app/actions/auth";

export interface AuthUser {
  id: string;
  email?: string;
  user_metadata?: {
    full_name?: string;
    name?: string;
    username?: string;
    avatar_url?: string;
    picture?: string;
    [key: string]: any;
  };
  app_metadata?: Record<string, any>;
  aud?: string;
  created_at?: string;
  [key: string]: any;
}

export interface AuthSession {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  token_type?: string;
  expires_in?: number;
  user: AuthUser;
  [key: string]: any;
}

// Backward-compatibility aliases for Supabase types
export type User = AuthUser;
export type Session = AuthSession;

export interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  profile: {
    id?: string;
    name: string;
    email: string;
    avatar: string;
    username: string;
    phone?: string;
  } | null;
  refreshProfile: () => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (identifier: string, password: string) => Promise<{ error: string | null }>;
  signUpWithEmail: (
    email: string,
    password: string,
    username: string,
    fullName: string
  ) => Promise<{ error: string | null; message?: string | null; requiresConfirmation?: boolean }>;
  confirmEmail: (
    email: string,
    code: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  resendVerificationCode: (
    email: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  requestPasswordReset: (
    email: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  confirmPasswordReset: (
    email: string,
    code: string,
    newPassword: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  // Compatibility aliases
  resendConfirmationCode: (
    email: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  forgotPassword: (
    email: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  resetPassword: (
    email: string,
    code: string,
    newPassword: string
  ) => Promise<{ error: string | null; success?: boolean; message?: string }>;
  signOut: () => Promise<void>;
  getUserMeta: () => { name: string; email: string; avatar: string; username: string };
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({
  children,
  initialSession = null,
}: {
  children: React.ReactNode;
  initialSession?: Session | null;
}) {
  const [session, setSession] = useState<Session | null>(initialSession);
  const user = session?.user ?? null;
  const [loading, setLoading] = useState(!initialSession);
  const [profile, setProfile] = useState<{
    id?: string;
    name: string;
    email: string;
    avatar: string;
    username: string;
    phone?: string;
  } | null>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    let isMounted = true;

    const initSession = async () => {
      // 1. Mock session for test environments
      if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
        const mockUser: User = {
          id: "12345678-1234-1234-1234-123456789012",
          email: "testuser@example.com",
          user_metadata: { full_name: "Test User", username: "testuser" },
        };
        const mockSession: Session = {
          access_token: "mock-token",
          token_type: "bearer",
          user: mockUser,
        };
        if (isMounted) {
          setSession(mockSession);
          setLoading(false);
          if (pathname === "/" || pathname === "/login") {
            router.push("/dashboard");
          }
        }
        return;
      }

      // 2. Authoritative server-side session check (Cognito cookies)
      try {
        const { session: serverSession } = await getCurrentSession();
        if (isMounted) {
          if (serverSession) {
            setSession(serverSession);
            if (pathname === "/" || pathname === "/login") {
              router.push("/dashboard");
            }
          } else {
            setSession(initialSession);
          }
        }
      } catch (err) {
        console.warn("[Auth] Server session fetch error:", err);
        if (isMounted) {
          setSession(initialSession);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    initSession();

    return () => {
      isMounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshProfile = async () => {
    if (!user) {
      setProfile(null);
      return;
    }
    try {
      const p = await API.getMyProfile({ preferCache: false, userId: user.id });
      if (p) {
        setProfile({
          id: p.id,
          name: p.name || "",
          email: p.email || user.email || "",
          avatar: p.avatar_url || "",
          username: p.username || "",
          phone: p.phone || "",
        });
      }
    } catch (_) {}
  };

  useEffect(() => {
    if (!user) {
      setProfile(null);
      return;
    }

    // Instant render from user-scoped localStorage cache
    const cached = API.getCachedProfile ? API.getCachedProfile(24 * 60 * 60 * 1000, user.id) : null;
    if (cached) {
      setProfile({
        id: cached.id || user.id,
        name: cached.name || "",
        email: cached.email || user.email || "",
        avatar: cached.avatar_url || "",
        username: cached.username || "",
        phone: cached.phone || "",
      });
    } else {
      const meta = user.user_metadata || {};
      setProfile({
        id: user.id,
        name: meta.full_name || meta.name || (user.email ? user.email.split("@")[0] : "User"),
        email: user.email || "",
        avatar: meta.avatar_url || meta.picture || "",
        username: meta.username || (user.email ? user.email.split("@")[0] : ""),
      });
    }

    // Refresh profile in background from server
    refreshProfile();

    const handleProfileUpdate = (event: Event) => {
      const customEvent = event as CustomEvent;
      const data = customEvent.detail;
      if (!data) {
        setProfile(null);
      } else {
        setProfile({
          id: data.id,
          name: data.name || "",
          email: data.email || user?.email || "",
          avatar: data.avatar_url || "",
          username: data.username || "",
          phone: data.phone || "",
        });
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("ipp_profile_updated", handleProfileUpdate);
      return () => {
        window.removeEventListener("ipp_profile_updated", handleProfileUpdate);
      };
    }
  }, [user]);

  const signInWithGoogle = async () => {
    if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
      setSession({
        access_token: "mock-token",
        token_type: "bearer",
        user: {
          id: "12345678-1234-1234-1234-123456789012",
          email: "testuser@example.com",
          user_metadata: { full_name: "Test User", username: "testuser" },
        },
      });
      router.push("/dashboard");
      return;
    }

    // Initiate Cognito Google OAuth with PKCE
    try {
      const res = await initiateCognitoGoogleAuth("/dashboard");
      if (res?.url) {
        window.location.href = res.url;
        return;
      }
      throw new Error("Unable to initialize Cognito Google authentication URL.");
    } catch (cognitoErr: any) {
      console.error("[Auth] Cognito Google sign-in failed:", cognitoErr);
      const msg = cognitoErr?.message || "Google sign-in is temporarily unavailable. Please try again.";
      alert(msg);
    }
  };

  const signInWithEmail = async (
    identifier: string,
    password: string
  ): Promise<{ error: string | null }> => {
    const cleanIdentifier = identifier.trim();

    if (!cleanIdentifier) {
      return { error: `Please enter your email address or username to sign in.` };
    }

    const formData = new FormData();
    formData.append("identifier", cleanIdentifier);
    formData.append("email", cleanIdentifier);
    formData.append("password", password);

    const result = await login(formData);

    if (result.error) {
      return { error: result.error };
    }

    // Refresh server session state
    try {
      const { session: newSession } = await getCurrentSession();
      if (newSession) {
        setSession(newSession);
      }
    } catch (_) {}

    window.location.replace("/dashboard");
    return { error: null };
  };

  const signUpWithEmail = async (
    email: string,
    password: string,
    username: string,
    fullName: string
  ): Promise<{ error: string | null; message?: string | null; requiresConfirmation?: boolean }> => {
    const formData = new FormData();
    formData.append("email", email);
    formData.append("password", password);
    formData.append("username", username);
    formData.append("fullName", fullName);

    const result = await signup(formData);

    if (result.error) {
      return { error: result.error };
    }

    if ((result as any).requiresConfirmation || (result as any).needsConfirmation) {
      return {
        error: null,
        message: (result as any).message,
        requiresConfirmation: true,
      };
    }

    if ((result as any).message) {
      return { error: null, message: (result as any).message };
    }

    // Refresh server session state
    try {
      const { session: newSession } = await getCurrentSession();
      if (newSession) {
        setSession(newSession);
      }
    } catch (_) {}

    window.location.replace("/dashboard");
    return { error: null };
  };

  const confirmEmail = async (
    email: string,
    code: string
  ): Promise<{ error: string | null; success?: boolean; message?: string }> => {
    try {
      const res = await serverConfirmEmail(email, code);
      return {
        error: res.error || null,
        success: res.success ?? !res.error,
        message: res.message,
      };
    } catch (err: any) {
      return {
        error: err?.message || "Failed to confirm email.",
        success: false,
      };
    }
  };

  const resendVerificationCode = async (
    email: string
  ): Promise<{ error: string | null; success?: boolean; message?: string }> => {
    try {
      const res = await serverResendVerificationCode(email);
      return {
        error: res.error || null,
        success: res.success ?? !res.error,
        message: res.message,
      };
    } catch (err: any) {
      return {
        error: err?.message || "Failed to resend verification code.",
        success: false,
      };
    }
  };

  const requestPasswordReset = async (
    email: string
  ): Promise<{ error: string | null; success?: boolean; message?: string }> => {
    try {
      const res = await serverRequestPasswordReset(email);
      return {
        error: res.error || null,
        success: res.success ?? !res.error,
        message: res.message,
      };
    } catch (err: any) {
      return {
        error: err?.message || "Failed to request password reset.",
        success: false,
      };
    }
  };

  const confirmPasswordReset = async (
    email: string,
    code: string,
    newPassword: string
  ): Promise<{ error: string | null; success?: boolean; message?: string }> => {
    try {
      const res = await serverConfirmPasswordReset(email, code, newPassword);
      return {
        error: res.error || null,
        success: res.success ?? !res.error,
        message: res.message,
      };
    } catch (err: any) {
      return {
        error: err?.message || "Failed to reset password.",
        success: false,
      };
    }
  };

  const signOut = async () => {
    let logoutUrl = "/login";
    try {
      const res = await logout();
      if (res?.logoutUrl) {
        logoutUrl = res.logoutUrl;
      }
      if (typeof window !== "undefined") {
        if (API && typeof API.clearCachedProfile === "function") {
          API.clearCachedProfile();
        } else {
          localStorage.removeItem("ipp_profile_cache_v1");
        }
        localStorage.removeItem("questionsPageUiState");
        localStorage.removeItem("questionsCustomFolderV1");
        sessionStorage.clear();
      }
    } catch (_) {}
    setSession(null);
    setProfile(null);
    window.location.replace(logoutUrl);
  };

  const getUserMeta = () => {
    if (!user) return { name: "User", email: "", avatar: "", username: "" };
    if (profile) {
      return {
        name: profile.name || (user.email ? user.email.split("@")[0] : "User"),
        email: profile.email || user.email || "",
        avatar: profile.avatar || "",
        username: profile.username || (user.email ? user.email.split("@")[0] : ""),
      };
    }
    const meta = user.user_metadata || {};
    let cached: any = null;
    try {
      if (typeof window !== "undefined" && API && typeof API.getCachedProfile === "function") {
        cached = API.getCachedProfile(24 * 60 * 60 * 1000, user.id);
      }
    } catch (_) {}

    const username =
      cached?.username || meta.username || (user.email ? user.email.split("@")[0] : "");
    const name =
      cached?.name ||
      meta.full_name ||
      meta.name ||
      (user.email ? user.email.split("@")[0] : "User");
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
        profile,
        refreshProfile,
        signInWithGoogle,
        signInWithEmail,
        signUpWithEmail,
        confirmEmail,
        resendVerificationCode,
        requestPasswordReset,
        confirmPasswordReset,
        resendConfirmationCode: resendVerificationCode,
        forgotPassword: requestPasswordReset,
        resetPassword: confirmPasswordReset,
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

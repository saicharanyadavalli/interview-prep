"use client";

import React, { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const { session, signInWithGoogle, signInWithEmailOrUsername, signUpWithEmail, loading } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  // Sign In state
  const [loginIdentifier, setLoginIdentifier] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  // Sign Up state
  const [signUpFullName, setSignUpFullName] = useState("");
  const [signUpUsername, setSignUpUsername] = useState("");
  const [signUpEmail, setSignUpEmail] = useState("");
  const [signUpPassword, setSignUpPassword] = useState("");
  const [signUpConfirmPassword, setSignUpConfirmPassword] = useState("");

  useEffect(() => {
    if (!loading && session) {
      router.push("/dashboard");
    }
  }, [session, loading, router]);

  const validatePassword = (pass: string): string | null => {
    if (pass.length < 8) {
      return "Password must be at least 8 characters long.";
    }
    if (!/[A-Z]/.test(pass)) {
      return "Password must contain at least 1 uppercase letter.";
    }
    if (!/[0-9]/.test(pass)) {
      return "Password must contain at least 1 number.";
    }
    if (!/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(pass)) {
      return "Password must contain at least 1 special character (!@#$%^&*...).";
    }
    return null;
  };

  const handleSignInSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!loginIdentifier.trim()) {
      setErrorMessage("Please enter your username or email address.");
      return;
    }
    if (!loginPassword) {
      setErrorMessage("Please enter your password.");
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await signInWithEmailOrUsername(loginIdentifier.trim(), loginPassword);
      if (res.error) {
        setErrorMessage(res.error);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSignUpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!signUpFullName.trim()) {
      setErrorMessage("Please enter your full name.");
      return;
    }
    if (!signUpUsername.trim()) {
      setErrorMessage("Please choose a username.");
      return;
    }
    if (signUpUsername.trim().length < 3) {
      setErrorMessage("Username must be at least 3 characters long.");
      return;
    }
    if (!/^[a-zA-Z0-9_]+$/.test(signUpUsername.trim())) {
      setErrorMessage("Username can only contain letters, numbers, and underscores.");
      return;
    }
    if (!signUpEmail.trim() || !signUpEmail.includes("@")) {
      setErrorMessage("Please enter a valid email address.");
      return;
    }

    const passError = validatePassword(signUpPassword);
    if (passError) {
      setErrorMessage(passError);
      return;
    }

    if (signUpPassword !== signUpConfirmPassword) {
      setErrorMessage("Passwords do not match. Please re-enter.");
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await signUpWithEmail(
        signUpEmail.trim(),
        signUpPassword,
        signUpUsername.trim(),
        signUpFullName.trim()
      );
      if (res.error) {
        setErrorMessage(res.error);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setErrorMessage(null);
    setIsSubmitting(true);
    try {
      await signInWithGoogle();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="login-page w-full">
      <div className="login-card mx-auto">
        <img className="brand-logo" src="/assets/logo-mark.svg" alt="Interview Assistant logo" />
        <h1>Interview Assistant</h1>
        <p className="subtitle">Sharpen your coding interview skills with AI-powered guidance</p>

        {/* Tab Selection */}
        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab ${mode === "signin" ? "active" : ""}`}
            onClick={() => { setMode("signin"); setErrorMessage(null); }}
          >
            Sign In
          </button>
          <button
            type="button"
            className={`auth-tab ${mode === "signup" ? "active" : ""}`}
            onClick={() => { setMode("signup"); setErrorMessage(null); }}
          >
            Sign Up
          </button>
        </div>

        {/* Error Banner */}
        {errorMessage && (
          <div className="auth-error-banner" role="alert">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Sign In Form */}
        {mode === "signin" ? (
          <form onSubmit={handleSignInSubmit} className="auth-form">
            <div className="form-group">
              <label htmlFor="loginIdentifier">Username or Email</label>
              <input
                id="loginIdentifier"
                type="text"
                className="form-control"
                placeholder="e.g. alex_coder or alex@example.com"
                value={loginIdentifier}
                onChange={(e) => setLoginIdentifier(e.target.value)}
                disabled={isSubmitting || loading}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="loginPassword">Password</label>
              <div className="password-input-wrapper">
                <input
                  id="loginPassword"
                  type={showPassword ? "text" : "password"}
                  className="form-control"
                  placeholder="••••••••"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  disabled={isSubmitting || loading}
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "🙈" : "👁️"}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full btn-auth-submit"
              disabled={isSubmitting || loading}
            >
              {isSubmitting ? "Signing in..." : "Sign In"}
            </button>
          </form>
        ) : (
          /* Sign Up Form */
          <form onSubmit={handleSignUpSubmit} className="auth-form">
            <div className="form-group">
              <label htmlFor="signUpFullName">Full Name</label>
              <input
                id="signUpFullName"
                type="text"
                className="form-control"
                placeholder="e.g. Alex Johnson"
                value={signUpFullName}
                onChange={(e) => setSignUpFullName(e.target.value)}
                disabled={isSubmitting || loading}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="signUpUsername">Username</label>
              <input
                id="signUpUsername"
                type="text"
                className="form-control"
                placeholder="e.g. alex_coder"
                value={signUpUsername}
                onChange={(e) => setSignUpUsername(e.target.value)}
                disabled={isSubmitting || loading}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="signUpEmail">Email Address</label>
              <input
                id="signUpEmail"
                type="email"
                className="form-control"
                placeholder="alex@example.com"
                value={signUpEmail}
                onChange={(e) => setSignUpEmail(e.target.value)}
                disabled={isSubmitting || loading}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="signUpPassword">Password</label>
              <div className="password-input-wrapper">
                <input
                  id="signUpPassword"
                  type={showPassword ? "text" : "password"}
                  className="form-control"
                  placeholder="••••••••"
                  value={signUpPassword}
                  onChange={(e) => setSignUpPassword(e.target.value)}
                  disabled={isSubmitting || loading}
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "🙈" : "👁️"}
                </button>
              </div>

              {/* Real-time Password Criteria Checklist */}
              <div className="password-criteria-checklist">
                <div className={`criteria-item ${signUpPassword.length >= 8 ? "satisfied" : ""}`}>
                  <span className="criteria-icon">{signUpPassword.length >= 8 ? "✓" : "○"}</span>
                  <span>At least 8 characters</span>
                </div>
                <div className={`criteria-item ${/[A-Z]/.test(signUpPassword) ? "satisfied" : ""}`}>
                  <span className="criteria-icon">{/[A-Z]/.test(signUpPassword) ? "✓" : "○"}</span>
                  <span>At least 1 uppercase letter (A-Z)</span>
                </div>
                <div className={`criteria-item ${/[0-9]/.test(signUpPassword) ? "satisfied" : ""}`}>
                  <span className="criteria-icon">{/[0-9]/.test(signUpPassword) ? "✓" : "○"}</span>
                  <span>At least 1 number (0-9)</span>
                </div>
                <div className={`criteria-item ${/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(signUpPassword) ? "satisfied" : ""}`}>
                  <span className="criteria-icon">{/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(signUpPassword) ? "✓" : "○"}</span>
                  <span>At least 1 special character (!@#$%^&*)</span>
                </div>
                {signUpConfirmPassword.length > 0 && (
                  <div className={`criteria-item ${signUpPassword.length > 0 && signUpPassword === signUpConfirmPassword ? "satisfied" : ""}`}>
                    <span className="criteria-icon">{signUpPassword.length > 0 && signUpPassword === signUpConfirmPassword ? "✓" : "○"}</span>
                    <span>Passwords match</span>
                  </div>
                )}
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="signUpConfirmPassword">Confirm Password</label>
              <input
                id="signUpConfirmPassword"
                type={showPassword ? "text" : "password"}
                className="form-control"
                placeholder="Re-enter password"
                value={signUpConfirmPassword}
                onChange={(e) => setSignUpConfirmPassword(e.target.value)}
                disabled={isSubmitting || loading}
                required
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full btn-auth-submit"
              disabled={isSubmitting || loading}
            >
              {isSubmitting ? "Creating Account..." : "Create Account"}
            </button>
          </form>
        )}

        <div className="login-divider">or continue with</div>

        <button
          className="btn btn-google"
          type="button"
          disabled={isSubmitting || loading}
          onClick={handleGoogleSignIn}
        >
          <svg width="20" height="20" viewBox="0 0 48 48">
            <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59A14.5 14.5 0 0 1 9.5 24c0-1.59.28-3.14.76-4.59l-7.98-6.19A23.99 23.99 0 0 0 0 24c0 3.77.9 7.35 2.56 10.53l7.97-5.94z"/>
            <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 5.94C6.51 42.62 14.62 48 24 48z"/>
          </svg>
          {isSubmitting ? "Connecting..." : "Sign in with Google"}
        </button>

        <p className="text-muted text-sm" style={{ marginTop: "1.5rem" }}>
          By signing in, you agree to practice responsibly 🚀
        </p>
      </div>
    </div>
  );
}

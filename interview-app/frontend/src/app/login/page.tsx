"use client";

import React, { useEffect, useState, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import {
  Loader2,
  CheckCircle2,
  AlertCircle,
  ArrowLeft,
  Mail,
  KeyRound,
  ShieldCheck,
  Eye,
  EyeOff,
  RefreshCw,
} from "lucide-react";

export type AuthMode =
  | "signin"
  | "signup"
  | "confirm"
  | "forgot_password"
  | "reset_password";

function PasswordCriteriaChecklist({
  password,
  confirmPassword,
}: {
  password: string;
  confirmPassword?: string;
}) {
  const hasMinLength = password.length >= 8;
  const hasUpper = /[A-Z]/.test(password);
  const hasNumber = /[0-9]/.test(password);
  const hasSpecial = /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password);
  const passwordsMatch =
    confirmPassword !== undefined &&
    confirmPassword.length > 0 &&
    password.length > 0 &&
    password === confirmPassword;

  return (
    <div
      className="password-criteria-checklist"
      role="region"
      aria-label="Password requirements"
    >
      <div className={`criteria-item ${hasMinLength ? "satisfied" : ""}`}>
        <span className="criteria-icon" aria-hidden="true">
          {hasMinLength ? "✓" : "○"}
        </span>
        <span>At least 8 characters</span>
      </div>
      <div className={`criteria-item ${hasUpper ? "satisfied" : ""}`}>
        <span className="criteria-icon" aria-hidden="true">
          {hasUpper ? "✓" : "○"}
        </span>
        <span>At least 1 uppercase letter (A-Z)</span>
      </div>
      <div className={`criteria-item ${hasNumber ? "satisfied" : ""}`}>
        <span className="criteria-icon" aria-hidden="true">
          {hasNumber ? "✓" : "○"}
        </span>
        <span>At least 1 number (0-9)</span>
      </div>
      <div className={`criteria-item ${hasSpecial ? "satisfied" : ""}`}>
        <span className="criteria-icon" aria-hidden="true">
          {hasSpecial ? "✓" : "○"}
        </span>
        <span>At least 1 special character (!@#$%^&*)</span>
      </div>
      {confirmPassword !== undefined && confirmPassword.length > 0 && (
        <div className={`criteria-item ${passwordsMatch ? "satisfied" : ""}`}>
          <span className="criteria-icon" aria-hidden="true">
            {passwordsMatch ? "✓" : "○"}
          </span>
          <span>Passwords match</span>
        </div>
      )}
    </div>
  );
}

export default function LoginPage() {
  const {
    session,
    signInWithGoogle,
    signInWithEmail,
    signUpWithEmail,
    confirmEmail,
    resendConfirmationCode,
    forgotPassword,
    resetPassword,
    loading,
  } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<AuthMode>("signin");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const redirectingRef = useRef(false);

  // Sign In state
  const [loginIdentifier, setLoginIdentifier] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  // Sign Up state
  const [signUpFullName, setSignUpFullName] = useState("");
  const [signUpUsername, setSignUpUsername] = useState("");
  const [signUpEmail, setSignUpEmail] = useState("");
  const [signUpPassword, setSignUpPassword] = useState("");
  const [signUpConfirmPassword, setSignUpConfirmPassword] = useState("");

  // Email Confirmation state
  const [confirmEmailAddress, setConfirmEmailAddress] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [resendCooldown, setResendCooldown] = useState(0);
  const [isResending, setIsResending] = useState(false);
  const [isEditingConfirmEmail, setIsEditingConfirmEmail] = useState(false);

  // Forgot Password state
  const [forgotEmail, setForgotEmail] = useState("");

  // Reset Password state
  const [resetEmail, setResetEmail] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");

  // Cooldown countdown timer for code resend
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const interval = setInterval(() => {
      setResendCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [resendCooldown]);

  // Session redirect
  useEffect(() => {
    if (!loading && session && !redirectingRef.current) {
      redirectingRef.current = true;
      router.replace("/dashboard");
    }
  }, [session, loading, router]);

  // Parse URL query parameters for mode and status
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const modeParam = params.get("mode") || params.get("tab");
      if (
        modeParam === "signup" ||
        modeParam === "confirm" ||
        modeParam === "forgot_password" ||
        modeParam === "reset_password"
      ) {
        setMode(modeParam as AuthMode);
      }

      const emailParam = params.get("email");
      if (emailParam) {
        const decodedEmail = decodeURIComponent(emailParam).trim();
        setLoginIdentifier(decodedEmail);
        setConfirmEmailAddress(decodedEmail);
        setForgotEmail(decodedEmail);
        setResetEmail(decodedEmail);
      }

      const errorParam = params.get("error");
      if (
        errorParam &&
        errorParam !== "auth-code-error" &&
        errorParam !== "env-missing"
      ) {
        setErrorMessage(decodeURIComponent(errorParam));
      }
    }
  }, []);

  const switchMode = (newMode: AuthMode) => {
    setMode(newMode);
    setErrorMessage(null);
    setSuccessMessage(null);
    setShowPassword(false);
    setShowConfirmPassword(false);

    // Contextual prefilling
    if (newMode === "forgot_password") {
      if (loginIdentifier.includes("@") && !forgotEmail) {
        setForgotEmail(loginIdentifier.trim());
      }
    } else if (newMode === "reset_password") {
      if (forgotEmail && !resetEmail) {
        setResetEmail(forgotEmail.trim());
      } else if (loginIdentifier.includes("@") && !resetEmail) {
        setResetEmail(loginIdentifier.trim());
      }
    } else if (newMode === "confirm") {
      if (signUpEmail && !confirmEmailAddress) {
        setConfirmEmailAddress(signUpEmail.trim());
      } else if (loginIdentifier.includes("@") && !confirmEmailAddress) {
        setConfirmEmailAddress(loginIdentifier.trim());
      }
    }
  };

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

  // --- 1. Sign In Submission ---
  const handleSignInSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    const cleanIdentifier = loginIdentifier.trim();
    if (!cleanIdentifier) {
      setErrorMessage("Please enter your email address or username.");
      return;
    }
    if (!loginPassword) {
      setErrorMessage("Please enter your password.");
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await signInWithEmail(cleanIdentifier, loginPassword);
      if (res.error) {
        // If account requires confirmation, offer smooth path to confirmation
        if (
          res.error.toLowerCase().includes("not confirmed") ||
          res.error.toLowerCase().includes("confirm your account")
        ) {
          if (cleanIdentifier.includes("@")) {
            setConfirmEmailAddress(cleanIdentifier);
          }
          setErrorMessage(res.error);
          return;
        }
        setErrorMessage(res.error);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- 2. Sign Up Submission ---
  const handleSignUpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    const cleanFullName = signUpFullName.trim();
    const cleanUsername = signUpUsername.trim();
    const cleanEmail = signUpEmail.trim().toLowerCase();

    if (!cleanFullName) {
      setErrorMessage("Please enter your full name.");
      return;
    }
    if (!cleanUsername) {
      setErrorMessage("Please choose a username.");
      return;
    }
    if (cleanUsername.length < 3) {
      setErrorMessage("Username must be at least 3 characters long.");
      return;
    }
    if (!/^[a-zA-Z0-9_]+$/.test(cleanUsername)) {
      setErrorMessage("Username can only contain letters, numbers, and underscores.");
      return;
    }
    if (!cleanEmail || !cleanEmail.includes("@")) {
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
        cleanEmail,
        signUpPassword,
        cleanUsername,
        cleanFullName
      );

      if (res.error) {
        setErrorMessage(res.error);
      } else if (
        res.requiresConfirmation ||
        (res.message && res.message.toLowerCase().includes("confirm"))
      ) {
        // Smooth transition to email verification mode
        setConfirmEmailAddress(cleanEmail);
        setResendCooldown(30);
        setSuccessMessage(
          res.message ||
            `Account created! A 6-digit verification code was sent to ${cleanEmail}.`
        );
        setMode("confirm");
      } else if (res.message) {
        setSuccessMessage(res.message);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- 3. Confirm Email Submission ---
  const handleConfirmSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    const targetEmail = confirmEmailAddress.trim().toLowerCase();
    const cleanCode = verificationCode.trim();

    if (!targetEmail || !targetEmail.includes("@")) {
      setErrorMessage("Please enter a valid email address.");
      return;
    }
    if (!cleanCode || cleanCode.length < 6) {
      setErrorMessage("Please enter the complete 6-digit verification code.");
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await confirmEmail(targetEmail, cleanCode);
      if (res.error) {
        setErrorMessage(res.error);
      } else {
        // Success: transition to sign in view with prefilled identifier
        setLoginIdentifier(targetEmail);
        setVerificationCode("");
        setSuccessMessage(
          res.message || "Email verified successfully! You can now sign in."
        );
        setMode("signin");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- Resend Confirmation Code ---
  const handleResendCode = async () => {
    if (resendCooldown > 0 || isResending) return;

    const targetEmail = confirmEmailAddress.trim().toLowerCase();
    if (!targetEmail || !targetEmail.includes("@")) {
      setErrorMessage("Please enter a valid email address to receive the code.");
      return;
    }

    setIsResending(true);
    setErrorMessage(null);
    try {
      const res = await resendConfirmationCode(targetEmail);
      if (res.error) {
        setErrorMessage(res.error);
      } else {
        setResendCooldown(30);
        setSuccessMessage(
          res.message || `A new verification code has been sent to ${targetEmail}.`
        );
      }
    } finally {
      setIsResending(false);
    }
  };

  // --- 4. Forgot Password Submission ---
  const handleForgotPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    const cleanEmail = forgotEmail.trim().toLowerCase();
    if (!cleanEmail || !cleanEmail.includes("@")) {
      setErrorMessage("Please enter your registered email address.");
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await forgotPassword(cleanEmail);
      if (res.error) {
        setErrorMessage(res.error);
      } else {
        // Smooth transition to Reset Password view
        setResetEmail(cleanEmail);
        setSuccessMessage(
          res.message ||
            `Password reset code sent! Please check your inbox and enter the code below.`
        );
        setMode("reset_password");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- 5. Reset Password Submission ---
  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    const cleanEmail = resetEmail.trim().toLowerCase();
    const cleanCode = resetCode.trim();

    if (!cleanEmail || !cleanEmail.includes("@")) {
      setErrorMessage("Please enter your email address.");
      return;
    }
    if (!cleanCode || cleanCode.length < 6) {
      setErrorMessage("Please enter the 6-digit reset code from your email.");
      return;
    }

    const passError = validatePassword(newPassword);
    if (passError) {
      setErrorMessage(passError);
      return;
    }

    if (newPassword !== confirmNewPassword) {
      setErrorMessage("Passwords do not match. Please re-enter.");
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await resetPassword(cleanEmail, cleanCode, newPassword);
      if (res.error) {
        setErrorMessage(res.error);
      } else {
        // Success: transition back to sign in
        setLoginIdentifier(cleanEmail);
        setResetCode("");
        setNewPassword("");
        setConfirmNewPassword("");
        setSuccessMessage(
          res.message ||
            "Password reset successfully! Please sign in with your new password."
        );
        setMode("signin");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- Google Sign In ---
  const handleGoogleSignIn = async () => {
    setErrorMessage(null);
    setSuccessMessage(null);
    setIsSubmitting(true);
    try {
      await signInWithGoogle();
    } finally {
      setIsSubmitting(false);
    }
  };

  const getSubheading = () => {
    switch (mode) {
      case "signin":
      case "signup":
        return "Sharpen your coding interview skills with AI-powered guidance";
      case "confirm":
        return "Enter the 6-digit verification code sent to your email";
      case "forgot_password":
        return "We'll send a password reset code to your registered email";
      case "reset_password":
        return "Choose a new secure password for your account";
      default:
        return "";
    }
  };

  return (
    <div className="login-page w-full">
      <div className="login-card mx-auto">
        {/* Brand Header */}
        <Link
          href="/"
          style={{ display: "inline-block", textDecoration: "none", color: "inherit" }}
          aria-label="Return to home page"
          title="Interview Assistant"
        >
          <Image
            className="brand-logo"
            src="/assets/logo-mark.svg"
            alt="Interview Assistant logo"
            width={48}
            height={48}
            priority
          />
          <h1>Interview Assistant</h1>
        </Link>
        <p className="subtitle">{getSubheading()}</p>

        {/* Tab Selection: Sign In vs Sign Up (only on main auth views) */}
        {mode === "signin" || mode === "signup" ? (
          <div className="auth-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "signin"}
              className={`auth-tab ${mode === "signin" ? "active" : ""}`}
              onClick={() => switchMode("signin")}
            >
              Sign In
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "signup"}
              className={`auth-tab ${mode === "signup" ? "active" : ""}`}
              onClick={() => switchMode("signup")}
            >
              Sign Up
            </button>
          </div>
        ) : (
          <div className="text-left">
            <button
              type="button"
              className="auth-back-link"
              onClick={() => switchMode("signin")}
            >
              <ArrowLeft size={16} />
              <span>Back to Sign In</span>
            </button>
          </div>
        )}

        {/* Error Banner */}
        {errorMessage && (
          <div className="auth-error-banner" role="alert" aria-live="assertive">
            <AlertCircle size={18} className="shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Success Banner */}
        {successMessage && (
          <div className="auth-success-banner" role="status" aria-live="polite">
            <CheckCircle2 size={18} className="shrink-0" />
            <span>{successMessage}</span>
          </div>
        )}

        {/* ── Mode 1: Sign In ── */}
        {mode === "signin" && (
          <>
            <form onSubmit={handleSignInSubmit} className="auth-form">
              <div className="form-group">
                <label htmlFor="loginIdentifier">Email or Username</label>
                <input
                  id="loginIdentifier"
                  type="text"
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  className="form-control"
                  placeholder="e.g. alex@example.com or alex_coder"
                  value={loginIdentifier}
                  onChange={(e) => setLoginIdentifier(e.target.value)}
                  disabled={isSubmitting || loading}
                  required
                />
              </div>

              <div className="form-group">
                <div className="flex items-center justify-between" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label htmlFor="loginPassword">Password</label>
                  <button
                    type="button"
                    className="auth-link text-xs"
                    onClick={() => switchMode("forgot_password")}
                    tabIndex={0}
                  >
                    Forgot password?
                  </button>
                </div>
                <div className="password-input-wrapper">
                  <input
                    id="loginPassword"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
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
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                className="btn btn-primary w-full btn-auth-submit"
                disabled={isSubmitting || loading}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="animate-spin" size={16} />
                    <span>Signing in...</span>
                  </>
                ) : (
                  "Sign In"
                )}
              </button>
            </form>

            <div className="login-divider">or continue with</div>

            <button
              className="btn btn-google"
              type="button"
              disabled={isSubmitting || loading}
              onClick={handleGoogleSignIn}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="animate-spin" size={18} />
                  <span>Connecting...</span>
                </>
              ) : (
                <>
                  <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
                    <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                    <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                    <path fill="#FBBC05" d="M10.53 28.59A14.5 14.5 0 0 1 9.5 24c0-1.59.28-3.14.76-4.59l-7.98-6.19A23.99 23.99 0 0 0 0 24c0 3.77.9 7.35 2.56 10.53l7.97-5.94z"/>
                    <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 5.94C6.51 42.62 14.62 48 24 48z"/>
                  </svg>
                  <span>Continue with Google</span>
                </>
              )}
            </button>

            <p className="auth-nav-toggle">
              Don&apos;t have an account?{" "}
              <button
                type="button"
                className="auth-link font-semibold"
                onClick={() => switchMode("signup")}
              >
                Sign up
              </button>
            </p>
          </>
        )}

        {/* ── Mode 2: Sign Up ── */}
        {mode === "signup" && (
          <>
            <form onSubmit={handleSignUpSubmit} className="auth-form">
              <div className="form-group">
                <label htmlFor="signUpFullName">Full Name</label>
                <input
                  id="signUpFullName"
                  type="text"
                  autoComplete="name"
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
                  autoComplete="username"
                  autoCapitalize="none"
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
                  autoComplete="email"
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
                    autoComplete="new-password"
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
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>

                {/* Real-time Password Criteria Checklist */}
                <PasswordCriteriaChecklist
                  password={signUpPassword}
                  confirmPassword={signUpConfirmPassword}
                />
              </div>

              <div className="form-group">
                <label htmlFor="signUpConfirmPassword">Confirm Password</label>
                <div className="password-input-wrapper">
                  <input
                    id="signUpConfirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    autoComplete="new-password"
                    className="form-control"
                    placeholder="Re-enter password"
                    value={signUpConfirmPassword}
                    onChange={(e) => setSignUpConfirmPassword(e.target.value)}
                    disabled={isSubmitting || loading}
                    required
                  />
                  <button
                    type="button"
                    className="password-toggle-btn"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                    title={showConfirmPassword ? "Hide password" : "Show password"}
                  >
                    {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                className="btn btn-primary w-full btn-auth-submit"
                disabled={isSubmitting || loading}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="animate-spin" size={16} />
                    <span>Creating Account...</span>
                  </>
                ) : (
                  "Create Account"
                )}
              </button>
            </form>

            <div className="login-divider">or continue with</div>

            <button
              className="btn btn-google"
              type="button"
              disabled={isSubmitting || loading}
              onClick={handleGoogleSignIn}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="animate-spin" size={18} />
                  <span>Connecting...</span>
                </>
              ) : (
                <>
                  <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
                    <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                    <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                    <path fill="#FBBC05" d="M10.53 28.59A14.5 14.5 0 0 1 9.5 24c0-1.59.28-3.14.76-4.59l-7.98-6.19A23.99 23.99 0 0 0 0 24c0 3.77.9 7.35 2.56 10.53l7.97-5.94z"/>
                    <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 5.94C6.51 42.62 14.62 48 24 48z"/>
                  </svg>
                  <span>Continue with Google</span>
                </>
              )}
            </button>

            <p className="auth-nav-toggle">
              Already have an account?{" "}
              <button
                type="button"
                className="auth-link font-semibold"
                onClick={() => switchMode("signin")}
              >
                Sign in
              </button>
            </p>
          </>
        )}

        {/* ── Mode 3: Email Confirmation ── */}
        {mode === "confirm" && (
          <form onSubmit={handleConfirmSubmit} className="auth-form">
            <div className="text-center mb-2" style={{ textAlign: "center" }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "48px",
                  height: "48px",
                  borderRadius: "50%",
                  background: "var(--teal-soft)",
                  color: "var(--teal)",
                  marginBottom: "0.75rem",
                }}
              >
                <Mail size={24} />
              </div>
              <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--ink)" }}>
                Verify your email
              </h2>
              <p className="form-hint" style={{ marginTop: "0.35rem" }}>
                We sent a 6-digit verification code to:
              </p>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  marginTop: "0.25rem",
                  fontWeight: 600,
                  color: "var(--ink)",
                }}
              >
                <span>{confirmEmailAddress || "your email"}</span>
                <button
                  type="button"
                  className="auth-link text-xs"
                  onClick={() => setIsEditingConfirmEmail(!isEditingConfirmEmail)}
                >
                  {isEditingConfirmEmail ? "Done" : "Edit"}
                </button>
              </div>
            </div>

            {isEditingConfirmEmail && (
              <div className="form-group">
                <label htmlFor="confirmEmailAddress">Email Address</label>
                <input
                  id="confirmEmailAddress"
                  type="email"
                  className="form-control"
                  placeholder="alex@example.com"
                  value={confirmEmailAddress}
                  onChange={(e) => setConfirmEmailAddress(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
              </div>
            )}

            <div className="form-group">
              <label htmlFor="verificationCode" style={{ textAlign: "center", display: "block" }}>
                6-Digit Verification Code
              </label>
              <input
                id="verificationCode"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                className="form-control auth-code-input"
                placeholder="123456"
                value={verificationCode}
                onChange={(e) =>
                  setVerificationCode(e.target.value.replace(/[^0-9A-Za-z]/g, "").slice(0, 6))
                }
                disabled={isSubmitting}
                autoFocus
                required
              />
              <span className="form-hint" style={{ textAlign: "center", display: "block" }}>
                Enter the verification code from your email inbox or spam folder.
              </span>
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full btn-auth-submit"
              disabled={isSubmitting || verificationCode.trim().length < 6}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="animate-spin" size={16} />
                  <span>Verifying...</span>
                </>
              ) : (
                "Confirm Email"
              )}
            </button>

            <div className="auth-resend-wrapper">
              <span>Didn&apos;t receive a code?</span>
              <button
                type="button"
                className="auth-link"
                disabled={resendCooldown > 0 || isResending}
                onClick={handleResendCode}
              >
                {isResending ? (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
                    <RefreshCw className="animate-spin" size={12} />
                    <span>Resending...</span>
                  </span>
                ) : resendCooldown > 0 ? (
                  `Resend in ${resendCooldown}s`
                ) : (
                  "Resend Code"
                )}
              </button>
            </div>
          </form>
        )}

        {/* ── Mode 4: Forgot Password ── */}
        {mode === "forgot_password" && (
          <form onSubmit={handleForgotPasswordSubmit} className="auth-form">
            <div className="text-center mb-2" style={{ textAlign: "center" }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "48px",
                  height: "48px",
                  borderRadius: "50%",
                  background: "var(--teal-soft)",
                  color: "var(--teal)",
                  marginBottom: "0.75rem",
                }}
              >
                <KeyRound size={24} />
              </div>
              <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--ink)" }}>
                Reset your password
              </h2>
              <p className="form-hint" style={{ marginTop: "0.35rem" }}>
                Enter your account email and we&apos;ll send you a password reset code.
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="forgotEmail">Email Address</label>
              <input
                id="forgotEmail"
                type="email"
                autoComplete="email"
                className="form-control"
                placeholder="alex@example.com"
                value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
                disabled={isSubmitting}
                autoFocus
                required
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full btn-auth-submit"
              disabled={isSubmitting || !forgotEmail.trim()}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="animate-spin" size={16} />
                  <span>Sending Code...</span>
                </>
              ) : (
                "Send Reset Code"
              )}
            </button>
          </form>
        )}

        {/* ── Mode 5: Reset Password ── */}
        {mode === "reset_password" && (
          <form onSubmit={handleResetPasswordSubmit} className="auth-form">
            <div className="text-center mb-2" style={{ textAlign: "center" }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "48px",
                  height: "48px",
                  borderRadius: "50%",
                  background: "var(--teal-soft)",
                  color: "var(--teal)",
                  marginBottom: "0.75rem",
                }}
              >
                <ShieldCheck size={24} />
              </div>
              <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--ink)" }}>
                Set new password
              </h2>
              <p className="form-hint" style={{ marginTop: "0.35rem" }}>
                Enter the code sent to your email and your new password.
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="resetEmail">Email Address</label>
              <input
                id="resetEmail"
                type="email"
                autoComplete="email"
                className="form-control"
                placeholder="alex@example.com"
                value={resetEmail}
                onChange={(e) => setResetEmail(e.target.value)}
                disabled={isSubmitting}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="resetCode" style={{ textAlign: "center", display: "block" }}>
                6-Digit Reset Code
              </label>
              <input
                id="resetCode"
                type="text"
                inputMode="numeric"
                maxLength={6}
                className="form-control auth-code-input"
                placeholder="123456"
                value={resetCode}
                onChange={(e) =>
                  setResetCode(e.target.value.replace(/[^0-9A-Za-z]/g, "").slice(0, 6))
                }
                disabled={isSubmitting}
                autoFocus
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="newPassword">New Password</label>
              <div className="password-input-wrapper">
                <input
                  id="newPassword"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  className="form-control"
                  placeholder="••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>

              {/* Real-time Password Criteria Checklist */}
              <PasswordCriteriaChecklist
                password={newPassword}
                confirmPassword={confirmNewPassword}
              />
            </div>

            <div className="form-group">
              <label htmlFor="confirmNewPassword">Confirm New Password</label>
              <div className="password-input-wrapper">
                <input
                  id="confirmNewPassword"
                  type={showConfirmPassword ? "text" : "password"}
                  autoComplete="new-password"
                  className="form-control"
                  placeholder="Re-enter new password"
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                  title={showConfirmPassword ? "Hide password" : "Show password"}
                >
                  {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full btn-auth-submit"
              disabled={isSubmitting || resetCode.trim().length < 6}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="animate-spin" size={16} />
                  <span>Resetting Password...</span>
                </>
              ) : (
                "Reset Password"
              )}
            </button>
          </form>
        )}

        <p className="text-muted text-sm" style={{ marginTop: "1.5rem" }}>
          By signing in, you agree to practice responsibly 🚀
        </p>
      </div>
    </div>
  );
}

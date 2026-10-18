import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

describe('Login Page & Auth UX Specialist Suite', () => {
  const loginPagePath = path.resolve(__dirname, '../src/app/login/page.tsx');
  const authContextPath = path.resolve(__dirname, '../src/lib/auth.tsx');
  const authActionsPath = path.resolve(__dirname, '../src/app/actions/auth.ts');
  const globalsCssPath = path.resolve(__dirname, '../src/app/globals.css');

  describe('Login Page File Existence and Core Structure', () => {
    it('verifies login/page.tsx exists and is a client component', () => {
      assert.ok(fs.existsSync(loginPagePath), 'login/page.tsx must exist');
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /^"use client";/, 'Must have "use client" directive at top');
    });

    it('verifies brand header layout and return link to home page', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /<Link[^>]*href="\/"[^>]*aria-label="Return to home page"/);
      assert.match(content, /Interview Assistant/);
      assert.match(content, /logo-mark\.svg/);
    });

    it('supports all 5 required authentication modes in AuthMode union', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /"signin"/);
      assert.match(content, /"signup"/);
      assert.match(content, /"confirm"/);
      assert.match(content, /"forgot_password"/);
      assert.match(content, /"reset_password"/);
    });
  });

  describe('Sign In (signin) Mode UX', () => {
    it('provides email or username input and password input with toggle', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /id="loginIdentifier"/);
      assert.match(content, /id="loginPassword"/);
      assert.match(content, /aria-label=\{showPassword \? "Hide password" : "Show password"\}/);
    });

    it('provides "Forgot password?" action link opening the forgot password view', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /switchMode\("forgot_password"\)/);
      assert.match(content, /Forgot password\?/);
    });

    it('provides "Sign In" submit button with loading spinner', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /<Loader2 className="animate-spin" size=\{16\} \/>/);
      assert.match(content, /Signing in\.\.\./);
      assert.match(content, /"Sign In"/);
    });

    it('provides "Continue with Google" button for Cognito Google OAuth', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /btn-google/);
      assert.match(content, /handleGoogleSignIn/);
      assert.match(content, /Continue with Google/);
    });

    it('provides "Don\'t have an account? Sign up" toggle link', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /Don't have an account\?|Don&apos;t have an account\?/);
      assert.match(content, /switchMode\("signup"\)/);
    });
  });

  describe('Sign Up (signup) Mode UX', () => {
    it('provides full name, username, email, password, and confirm password fields', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /id="signUpFullName"/);
      assert.match(content, /id="signUpUsername"/);
      assert.match(content, /id="signUpEmail"/);
      assert.match(content, /id="signUpPassword"/);
      assert.match(content, /id="signUpConfirmPassword"/);
    });

    it('implements real-time password criteria checklist (8+ chars, uppercase, number, special char)', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /password\.length >= 8/);
      assert.match(content, /\/\[A-Z\]\/\.test\(password\)/);
      assert.match(content, /\/\[0-9\]\/\.test\(password\)/);
      assert.ok(content.includes("[!@#$%^&*()_+\\-=\\[\\]{}|;:,.<>?]"));
      assert.match(content, /At least 8 characters/);
      assert.match(content, /At least 1 uppercase letter \(A-Z\)/);
      assert.match(content, /At least 1 number \(0-9\)/);
      assert.match(content, /At least 1 special character \(!@#\$%\^&\*\)/);
      assert.match(content, /Passwords match/);
    });

    it('smoothly transitions to email confirmation view when confirmation is required', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /setMode\("confirm"\)/);
      assert.match(content, /setConfirmEmailAddress\(cleanEmail\)/);
      assert.match(content, /setResendCooldown\(30\)/);
    });
  });

  describe('Email Confirmation (confirm) Mode UX', () => {
    it('displays "Verify your email" heading and the recipient email address', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /Verify your email/);
      assert.match(content, /confirmEmailAddress/);
    });

    it('provides 6-digit verification code input with formatted input mode', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /id="verificationCode"/);
      assert.match(content, /maxLength=\{6\}/);
      assert.match(content, /auth-code-input/);
      assert.match(content, /inputMode="numeric"/);
      assert.match(content, /autoComplete="one-time-code"/);
    });

    it('provides "Confirm Email" submit button with loading spinner', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /Verifying\.\.\./);
      assert.match(content, /"Confirm Email"/);
    });

    it('provides Resend Code action with 30-second cooldown timer', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /handleResendCode/);
      assert.match(content, /resendCooldown/);
      assert.match(content, /`Resend in \$\{resendCooldown\}s`/);
      assert.match(content, /"Resend Code"/);
    });

    it('provides "Back to Sign In" option and transitions to Sign In on success', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /Back to Sign In/);
      assert.match(content, /setMode\("signin"\)/);
      assert.match(content, /setLoginIdentifier\(targetEmail\)/);
    });
  });

  describe('Forgot Password (forgot_password) & Reset Password (reset_password) UX', () => {
    it('provides Forgot Password view with email input and "Send Reset Code" button', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /Reset your password/);
      assert.match(content, /id="forgotEmail"/);
      assert.match(content, /handleForgotPasswordSubmit/);
      assert.match(content, /"Send Reset Code"/);
      assert.match(content, /Sending Code\.\.\./);
      assert.match(content, /setMode\("reset_password"\)/);
    });

    it('provides Reset Password view with prefilled email, 6-digit code, and new password fields', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /Set new password/);
      assert.match(content, /id="resetEmail"/);
      assert.match(content, /id="resetCode"/);
      assert.match(content, /id="newPassword"/);
      assert.match(content, /id="confirmNewPassword"/);
      assert.match(content, /handleResetPasswordSubmit/);
      assert.match(content, /"Reset Password"/);
    });

    it('renders password criteria checklist during password reset', () => {
      const content = fs.readFileSync(loginPagePath, 'utf-8');
      assert.match(content, /<PasswordCriteriaChecklist[^>]*password=\{newPassword\}[^>]*confirmPassword=\{confirmNewPassword\}/);
    });
  });

  describe('CSS Semantic Variables & Theme Accessibility', () => {
    it('defines semantic CSS classes for auth banners and forms in globals.css', () => {
      const css = fs.readFileSync(globalsCssPath, 'utf-8');
      assert.match(css, /\.auth-error-banner\s*\{[^}]*color\s*:\s*var\(--red\)/);
      assert.match(css, /\.auth-success-banner\s*\{[^}]*color\s*:\s*var\(--green\)/);
      assert.match(css, /\.auth-link\s*\{[^}]*color\s*:\s*var\(--teal\)/);
      assert.match(css, /\.auth-code-input\s*\{[^}]*letter-spacing/);
      assert.match(css, /\.auth-back-link\s*\{/);
      assert.match(css, /\.password-criteria-checklist\s*\{[^}]*background\s*:\s*var\(--surface-soft\)/);
    });

    it('ensures light and dark themes define all required color variables', () => {
      const css = fs.readFileSync(globalsCssPath, 'utf-8');
      // Light theme tokens
      assert.match(css, /--paper:\s*#fffdf8/);
      assert.match(css, /--ink:\s*#1e1f24/);
      assert.match(css, /--teal:\s*#0f766e/);
      assert.match(css, /--line:\s*#e6dcc7/);
      assert.match(css, /--surface-soft:\s*#fffcf6/);

      // Dark theme tokens
      assert.match(css, /\[data-theme="dark"\]\s*\{[^}]*--paper:\s*#111827/);
      assert.match(css, /\[data-theme="dark"\]\s*\{[^}]*--ink:\s*#f3f4f6/);
      assert.match(css, /\[data-theme="dark"\]\s*\{[^}]*--teal:\s*#22d3ee/);
      assert.match(css, /\[data-theme="dark"\]\s*\{[^}]*--line:\s*#263447/);
      assert.match(css, /\[data-theme="dark"\]\s*\{[^}]*--surface-soft:\s*#0b1220/);
    });
  });

  describe('Server Actions & AuthContext Integration', () => {
    it('exports confirmation and password reset actions from app/actions/auth.ts', () => {
      const content = fs.readFileSync(authActionsPath, 'utf-8');
      assert.match(content, /export async function confirmEmail/);
      assert.match(content, /export async function resendVerificationCode/);
      assert.match(content, /export async function requestPasswordReset/);
      assert.match(content, /export async function confirmPasswordReset/);
      assert.match(content, /export (async function|const) confirmSignUp/);
      assert.match(content, /export (async function|const) resendConfirmationCode/);
      assert.match(content, /export (async function|const) forgotPassword/);
      assert.match(content, /export (async function|const) confirmForgotPassword/);
    });

    it('exposes complete auth methods in AuthContextType and useAuth() in lib/auth.tsx', () => {
      const content = fs.readFileSync(authContextPath, 'utf-8');
      assert.match(content, /confirmEmail:\s*\(/);
      assert.match(content, /resendConfirmationCode:\s*\(/);
      assert.match(content, /forgotPassword:\s*\(/);
      assert.match(content, /resetPassword:\s*\(/);
      assert.match(content, /signUpWithEmail:\s*\(/);
    });
  });
});

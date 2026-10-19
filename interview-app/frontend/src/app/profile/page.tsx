"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { UserAvatar } from "@/components/UserAvatar";
import { Spinner } from "@/components/Spinner";
import {
  validateAvatarFile,
  optimizeAvatarImage,
  MAX_AVATAR_BYTES,
} from "@/utils/avatar-validation";
import {
  User,
  Pencil,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Loader2,
  AlertTriangle,
  Trash2,
  RotateCcw,
  X,
} from "lucide-react";

type UploadState = "idle" | "validating" | "preview_ready" | "uploading" | "success" | "error";

export default function ProfilePage() {
  const router = useRouter();
  const { user, loading: authLoading, refreshProfile, signOut } = useAuth();

  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");

  // Status and async loading states
  const [statusText, setStatusText] = useState("Loading profile...");
  const [statusType, setStatusType] = useState<"info" | "success" | "error">("info");
  const [isSaving, setIsSaving] = useState(false);
  const [usernameError, setUsernameError] = useState<string | null>(null);

  // Danger Zone state
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [resetConfirmText, setResetConfirmText] = useState("");
  const [isResetting, setIsResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetSuccess, setResetSuccess] = useState<string | null>(null);

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Avatar upload state machine
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Deterministically clean up object URLs when previewUrl changes or component unmounts
  useEffect(() => {
    return () => {
      if (previewUrl && previewUrl.startsWith("blob:")) {
        try {
          URL.revokeObjectURL(previewUrl);
        } catch (_) {}
      }
    };
  }, [previewUrl]);

  // Load user profile on mount
  useEffect(() => {
    let mounted = true;
    if (authLoading) return;

    if (!user) {
      router.replace("/login?next=/profile");
      return;
    }

    setStatusText("Loading profile...");
    setStatusType("info");

    const loadData = async () => {
      try {
        // Fast path: load user-scoped cache immediately
        const cached = API.getCachedProfile ? API.getCachedProfile(12 * 60 * 60 * 1000, user.id) : null;
        if (cached && mounted) {
          setName(cached.name || "");
          setUsername(cached.username || "");
          setPhone(cached.phone || "");
          setEmail(cached.email || user.email || "");
          setAvatarUrl(cached.avatar_url || "");
          setStatusText("Profile loaded.");
          setStatusType("info");
        }

        // Authoritative fetch from server
        const profile = await API.getMyProfile({ preferCache: false, userId: user.id });
        if (mounted && profile) {
          setName(profile.name || "");
          setUsername(profile.username || "");
          setPhone(profile.phone || "");
          setEmail(profile.email || user.email || "");
          setAvatarUrl(profile.avatar_url || "");
          setStatusText("Profile loaded.");
          setStatusType("info");
        }
      } catch (err: any) {
        if (mounted) {
          setStatusText(`Could not load profile: ${err.message || "Unknown error"}`);
          setStatusType("error");
        }
      }
    };

    loadData();

    return () => {
      mounted = false;
    };
  }, [user, authLoading, router]);

  // Username validation
  const handleUsernameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value.toLowerCase().trim();
    setUsername(val);
    if (val && !/^[a-z0-9_]{3,50}$/.test(val)) {
      setUsernameError("Username must be 3-50 lowercase letters, numbers, or underscores.");
    } else {
      setUsernameError(null);
    }
  };

  // Phone number input sanitization (digits only, max 10)
  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const digitsOnly = String(e.target.value || "").replace(/\D+/g, "").slice(0, 10);
    setPhone(digitsOnly);
  };

  const handlePhonePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = (e.clipboardData.getData("text") || "").replace(/\D+/g, "").slice(0, 10);
    setPhone(pasted);
  };

  // Process and upload avatar file
  const processAndUploadAvatar = async (file: File) => {
    setUploadState("validating");
    setUploadError(null);
    setPendingFile(file);

    // 1. Client-side security and dimension validation
    const validation = await validateAvatarFile(file);
    if (!validation.valid) {
      setUploadState("error");
      setUploadError(validation.error || "Invalid image file.");
      return;
    }

    // 2. Generate immediate preview
    const localBlobUrl = URL.createObjectURL(file);
    setPreviewUrl(localBlobUrl);
    setUploadState("uploading");
    setStatusText("Optimizing and uploading avatar...");
    setStatusType("info");

    try {
      // 3. Optimize image to prevent excessive bandwidth
      const optimized = await optimizeAvatarImage(file, 1024, 0.88);

      // 4. Send to backend avatar upload endpoint
      const result = await API.uploadProfileAvatar(optimized);

      if (result && result.avatar_url) {
        setAvatarUrl(result.avatar_url);
        setUploadState("success");
        setPendingFile(null);
        setStatusText("Avatar uploaded and saved successfully.");
        setStatusType("success");

        // Revoke the temporary blob preview URL
        if (localBlobUrl) {
          try {
            URL.revokeObjectURL(localBlobUrl);
          } catch (_) {}
          setPreviewUrl(null);
        }

        if (refreshProfile) {
          refreshProfile();
        }
      } else {
        throw new Error(result?.error || "Failed to receive new avatar URL.");
      }
    } catch (err: any) {
      setUploadState("error");
      const message = err.message || "Failed to upload avatar.";
      setUploadError(message);
      setStatusText(`Avatar upload failed: ${message}`);
      setStatusType("error");
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleAvatarFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      processAndUploadAvatar(file);
    }
  };

  const handleRetryUpload = () => {
    if (pendingFile) {
      processAndUploadAvatar(pendingFile);
    } else if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // Save profile details
  const handleSave = async () => {
    if (usernameError) {
      setStatusText(usernameError);
      setStatusType("error");
      return;
    }

    setIsSaving(true);
    setStatusText("Saving profile...");
    setStatusType("info");

    try {
      const payload: Record<string, string> = {
        name: name.trim(),
        username: username.trim().toLowerCase(),
        phone: phone.trim(),
        avatar_url: avatarUrl.trim(),
      };

      const updated = await API.updateMyProfile(payload);
      if (updated) {
        setName(updated.name || "");
        setUsername(updated.username || "");
        setPhone(updated.phone || "");
        setEmail(updated.email || email);
        setAvatarUrl(updated.avatar_url || avatarUrl);
        setStatusText("Profile saved successfully.");
        setStatusType("success");
        if (refreshProfile) {
          refreshProfile();
        }
      }
    } catch (err: any) {
      const msg = err.message || "Failed to save profile.";
      setStatusText(`Save failed: ${msg}`);
      setStatusType("error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetProgress = async () => {
    if (resetConfirmText.trim() !== "RESET") {
      setResetError("Please type RESET in capital letters to confirm.");
      return;
    }

    setIsResetting(true);
    setResetError(null);
    try {
      const res = await API.resetUserProgress();
      if (res && res.success) {
        setResetSuccess("Your progress has been reset successfully. Account profile and settings were preserved.");
        setResetModalOpen(false);
        setResetConfirmText("");
        setStatusText("All progress reset successfully.");
        setStatusType("success");
        if (refreshProfile) {
          refreshProfile();
        }
      } else {
        throw new Error(res?.message || "Failed to reset progress.");
      }
    } catch (err: any) {
      setResetError(err.message || "An unexpected error occurred while resetting progress.");
    } finally {
      setIsResetting(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirmText.trim() !== "DELETE") {
      setDeleteError("Please type DELETE in capital letters to confirm.");
      return;
    }

    setIsDeleting(true);
    setDeleteError(null);
    try {
      const res = await API.deleteUserAccount();
      if (res && res.success) {
        setDeleteModalOpen(false);
        setDeleteConfirmText("");
        API.clearCachedProfile();
        await signOut();
      } else {
        throw new Error(res?.message || "Failed to delete account.");
      }
    } catch (err: any) {
      setDeleteError(err.message || "An unexpected error occurred while deleting your account.");
      setIsDeleting(false);
    }
  };

  const isBusy = isSaving || uploadState === "validating" || uploadState === "uploading" || isResetting || isDeleting;

  if (authLoading || !user) {
    return (
      <main className="main-content" style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Spinner text="Loading profile..." />
      </main>
    );
  }

  return (
    <main className="main-content">
      <div className="page-header">
        <h1 style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <User size={28} className="text-teal" /> Profile Settings
        </h1>
      </div>

      <section
        className="card-flat section"
        style={{
          padding: "1.75rem",
          background: "var(--paper)",
          borderRadius: "var(--radius-lg)",
          border: "1px solid var(--line)",
          maxWidth: "760px",
        }}
      >
        <div className="card-header" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "1.2rem", fontWeight: 600 }}>Account & Identity</h2>
          <p className="text-sm text-muted" style={{ marginTop: "0.25rem" }}>
            Manage your personal profile, handle, contact information, and avatar image.
          </p>
        </div>

        {/* Avatar Section */}
        <div
          className="avatar-management-section"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "1.5rem",
            padding: "1.25rem",
            background: "var(--bg)",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
            marginBottom: "1.5rem",
          }}
        >
          <div
            className="profile-avatar-container"
            style={{
              position: "relative",
              width: "96px",
              height: "96px",
              flexShrink: 0,
            }}
          >
            <UserAvatar
              src={previewUrl || avatarUrl}
              name={name}
              username={username}
              size={96}
              priority={true}
              alt="Profile avatar"
              style={{
                width: "96px",
                height: "96px",
                border: "2px solid var(--teal)",
                boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
              }}
            />

            {(uploadState === "validating" || uploadState === "uploading") && (
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: "50%",
                  background: "rgba(0,0,0,0.55)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#ffffff",
                }}
                aria-label="Processing avatar"
              >
                <Loader2 size={28} className="animate-spin" />
              </div>
            )}

            <button
              id="profileAvatarEditBtn"
              type="button"
              aria-label="Upload profile avatar"
              title="Change avatar picture"
              onClick={() => fileInputRef.current?.click()}
              disabled={isBusy}
              style={{
                position: "absolute",
                bottom: 0,
                right: 0,
                background: "var(--teal)",
                color: "#ffffff",
                border: "2px solid var(--paper)",
                borderRadius: "50%",
                width: "32px",
                height: "32px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: isBusy ? "not-allowed" : "pointer",
                boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
              }}
            >
              <Pencil size={14} />
            </button>

            <input
              id="profileAvatarFile"
              type="file"
              accept=".jpg,.jpeg,.png,.webp,.gif,image/jpeg,image/png,image/webp,image/gif"
              aria-label="Upload avatar image file"
              ref={fileInputRef}
              onChange={handleAvatarFileSelected}
              style={{ display: "none" }}
            />
          </div>

          <div style={{ flex: 1 }}>
            <h3 style={{ fontSize: "1rem", fontWeight: 600, margin: "0 0 0.25rem 0" }}>
              Profile Photo
            </h3>
            <p className="text-sm text-muted" style={{ margin: "0 0 0.5rem 0", fontSize: "0.85rem" }}>
              Accepted formats: JPG, PNG, WebP, GIF. Maximum file size: 5 MB.
            </p>

            {uploadState === "error" && uploadError && (
              <div
                role="alert"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  color: "var(--danger, #ef4444)",
                  fontSize: "0.85rem",
                  marginTop: "0.25rem",
                }}
              >
                <AlertCircle size={16} />
                <span>{uploadError}</span>
                {pendingFile && (
                  <button
                    type="button"
                    onClick={handleRetryUpload}
                    className="btn btn-sm btn-outline"
                    style={{
                      marginLeft: "0.5rem",
                      padding: "0.2rem 0.5rem",
                      fontSize: "0.75rem",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "0.25rem",
                    }}
                  >
                    <RefreshCw size={12} /> Retry
                  </button>
                )}
              </div>
            )}

            {uploadState === "success" && (
              <div
                role="status"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.35rem",
                  color: "var(--teal, #0f766e)",
                  fontSize: "0.85rem",
                }}
              >
                <CheckCircle size={15} />
                <span>Avatar updated!</span>
              </div>
            )}
          </div>
        </div>

        {/* Input Details */}
        <div
          className="form-row section"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "1.25rem",
            marginBottom: "1.5rem",
          }}
        >
          <div className="control-group" style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            <label htmlFor="profileName" style={{ fontWeight: 500, fontSize: "0.9rem" }}>
              Full Name
            </label>
            <input
              id="profileName"
              type="text"
              placeholder="e.g. John Doe"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isBusy}
              style={{
                padding: "0.6rem 0.85rem",
                borderRadius: "var(--radius)",
                border: "1px solid var(--line)",
                background: "var(--bg)",
                color: "var(--ink)",
                fontSize: "0.95rem",
              }}
            />
          </div>

          <div className="control-group" style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            <label htmlFor="profileUsername" style={{ fontWeight: 500, fontSize: "0.9rem" }}>
              Username
            </label>
            <input
              id="profileUsername"
              type="text"
              placeholder="e.g. johndoe"
              value={username}
              onChange={handleUsernameChange}
              disabled={isBusy}
              style={{
                padding: "0.6rem 0.85rem",
                borderRadius: "var(--radius)",
                border: usernameError ? "1px solid var(--danger, #ef4444)" : "1px solid var(--line)",
                background: "var(--bg)",
                color: "var(--ink)",
                fontSize: "0.95rem",
              }}
            />
            {usernameError && (
              <span style={{ color: "var(--danger, #ef4444)", fontSize: "0.78rem" }}>
                {usernameError}
              </span>
            )}
          </div>

          <div className="control-group" style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            <label htmlFor="profilePhone" style={{ fontWeight: 500, fontSize: "0.9rem" }}>
              Phone Number
            </label>
            <input
              id="profilePhone"
              type="text"
              inputMode="numeric"
              autoComplete="tel-national"
              pattern="[0-9]{10}"
              maxLength={10}
              placeholder="10-digit phone number"
              value={phone}
              onChange={handlePhoneChange}
              onPaste={handlePhonePaste}
              disabled={isBusy}
              style={{
                padding: "0.6rem 0.85rem",
                borderRadius: "var(--radius)",
                border: "1px solid var(--line)",
                background: "var(--bg)",
                color: "var(--ink)",
                fontSize: "0.95rem",
              }}
            />
          </div>
        </div>

        <div className="control-group section" style={{ display: "flex", flexDirection: "column", gap: "0.4rem", marginBottom: "1.75rem" }}>
          <label htmlFor="profileEmail" style={{ fontWeight: 500, fontSize: "0.9rem" }}>
            Email Address
          </label>
          <input
            id="profileEmail"
            type="email"
            disabled
            value={email}
            style={{
              padding: "0.6rem 0.85rem",
              borderRadius: "var(--radius)",
              border: "1px solid var(--line)",
              background: "var(--sidebar-bg)",
              color: "var(--muted)",
              fontSize: "0.95rem",
              cursor: "not-allowed",
            }}
          />
          <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
            Email address is managed by your authentication provider.
          </span>
        </div>

        {/* Status Bar */}
        <div
          className="status-bar section"
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "1rem 1.25rem",
            background: "var(--bg)",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
          }}
        >
          <div
            id="profileStatus"
            role={statusType === "error" ? "alert" : "status"}
            style={{
              fontSize: "0.9rem",
              fontWeight: 500,
              color:
                statusType === "error"
                  ? "var(--danger, #ef4444)"
                  : statusType === "success"
                  ? "var(--teal, #0f766e)"
                  : "var(--muted)",
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
            }}
          >
            {statusType === "error" && <AlertCircle size={16} />}
            {statusType === "success" && <CheckCircle size={16} />}
            <span>{statusText}</span>
          </div>

          <button
            id="saveProfileBtn"
            className="btn btn-primary"
            type="button"
            onClick={handleSave}
            disabled={isBusy || !user || Boolean(usernameError)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.55rem 1.25rem",
              fontWeight: 600,
            }}
          >
            {isSaving && <Loader2 size={16} className="animate-spin" />}
            Save Profile
          </button>
        </div>
      </section>

      {/* Danger Zone Section */}
      <section
        className="card-flat section"
        style={{
          padding: "1.75rem",
          background: "var(--paper)",
          borderRadius: "var(--radius-lg)",
          border: "1px solid var(--danger, #ef4444)",
          maxWidth: "760px",
          marginTop: "2rem",
        }}
      >
        <div className="card-header" style={{ marginBottom: "1.25rem" }}>
          <h2
            style={{
              fontSize: "1.2rem",
              fontWeight: 600,
              color: "var(--danger, #ef4444)",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <AlertTriangle size={20} /> Danger Zone
          </h2>
          <p className="text-sm text-muted" style={{ marginTop: "0.25rem" }}>
            Irreversible and destructive actions for your account data.
          </p>
        </div>

        {resetSuccess && (
          <div
            role="status"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.75rem 1rem",
              background: "rgba(15, 118, 110, 0.1)",
              border: "1px solid var(--teal, #0f766e)",
              borderRadius: "var(--radius)",
              color: "var(--teal, #0f766e)",
              fontSize: "0.9rem",
              marginBottom: "1.25rem",
            }}
          >
            <CheckCircle size={16} />
            <span>{resetSuccess}</span>
          </div>
        )}

        {/* Reset Progress Row */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "1.25rem",
            background: "var(--bg)",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
            marginBottom: "1rem",
            gap: "1.5rem",
            flexWrap: "wrap",
          }}
        >
          <div style={{ flex: 1, minWidth: "260px" }}>
            <h3 style={{ fontSize: "1rem", fontWeight: 600, margin: "0 0 0.25rem 0" }}>
              Reset Progress
            </h3>
            <p className="text-sm text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Reset all question progress, course completions, and practice history. Your account profile and settings will be preserved.
            </p>
          </div>
          <button
            id="openResetProgressModalBtn"
            type="button"
            className="btn btn-outline"
            onClick={() => {
              setResetConfirmText("");
              setResetError(null);
              setResetModalOpen(true);
            }}
            disabled={isBusy}
            style={{
              borderColor: "var(--line)",
              color: "var(--ink)",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.5rem 1rem",
              cursor: isBusy ? "not-allowed" : "pointer",
            }}
          >
            <RotateCcw size={15} />
            Reset Progress
          </button>
        </div>

        {/* Delete Account Row */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "1.25rem",
            background: "var(--bg)",
            borderRadius: "var(--radius)",
            border: "1px solid rgba(239, 68, 68, 0.3)",
            gap: "1.5rem",
            flexWrap: "wrap",
          }}
        >
          <div style={{ flex: 1, minWidth: "260px" }}>
            <h3 style={{ fontSize: "1rem", fontWeight: 600, margin: "0 0 0.25rem 0", color: "var(--danger, #ef4444)" }}>
              Delete Account
            </h3>
            <p className="text-sm text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Permanently delete your account and all associated data. This action cannot be undone.
            </p>
          </div>
          <button
            id="openDeleteAccountModalBtn"
            type="button"
            className="btn btn-danger"
            onClick={() => {
              setDeleteConfirmText("");
              setDeleteError(null);
              setDeleteModalOpen(true);
            }}
            disabled={isBusy}
            style={{
              background: "var(--danger, #ef4444)",
              color: "#ffffff",
              border: "none",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.5rem 1rem",
              borderRadius: "var(--radius)",
              cursor: isBusy ? "not-allowed" : "pointer",
            }}
          >
            <Trash2 size={15} />
            Delete Account
          </button>
        </div>
      </section>

      {/* Reset Progress Confirmation Modal */}
      {resetModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="resetModalTitle"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.65)",
            backdropFilter: "blur(2px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: "1rem",
          }}
        >
          <div
            style={{
              background: "var(--paper)",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--line)",
              maxWidth: "480px",
              width: "100%",
              padding: "1.5rem",
              boxShadow: "0 10px 25px rgba(0, 0, 0, 0.3)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <RotateCcw size={20} style={{ color: "var(--ink)" }} />
                <h3 id="resetModalTitle" style={{ fontSize: "1.15rem", fontWeight: 600, margin: 0 }}>
                  Reset All Progress
                </h3>
              </div>
              <button
                type="button"
                aria-label="Close modal"
                onClick={() => !isResetting && setResetModalOpen(false)}
                disabled={isResetting}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)" }}
              >
                <X size={18} />
              </button>
            </div>

            <p style={{ fontSize: "0.9rem", color: "var(--muted)", lineHeight: 1.5, marginBottom: "1rem" }}>
              Are you sure? This action will reset all question solving history, course lesson progress, and practice submissions. Your profile, username, comments, and settings will remain intact.
            </p>

            <div style={{ marginBottom: "1.25rem" }}>
              <label htmlFor="resetConfirmInput" style={{ display: "block", fontSize: "0.85rem", fontWeight: 500, marginBottom: "0.4rem" }}>
                Type <strong style={{ color: "var(--ink)" }}>RESET</strong> to confirm:
              </label>
              <input
                id="resetConfirmInput"
                type="text"
                placeholder="RESET"
                value={resetConfirmText}
                onChange={(e) => setResetConfirmText(e.target.value)}
                disabled={isResetting}
                style={{
                  width: "100%",
                  padding: "0.6rem 0.85rem",
                  borderRadius: "var(--radius)",
                  border: "1px solid var(--line)",
                  background: "var(--bg)",
                  color: "var(--ink)",
                  fontSize: "0.95rem",
                }}
              />
              {resetError && (
                <div role="alert" style={{ color: "var(--danger, #ef4444)", fontSize: "0.8rem", marginTop: "0.4rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                  <AlertCircle size={14} />
                  <span>{resetError}</span>
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setResetModalOpen(false)}
                disabled={isResetting}
                style={{ padding: "0.5rem 1rem", fontSize: "0.9rem" }}
              >
                Cancel
              </button>
              <button
                id="confirmResetProgressBtn"
                type="button"
                className="btn btn-primary"
                onClick={handleResetProgress}
                disabled={isResetting || resetConfirmText.trim() !== "RESET"}
                style={{
                  padding: "0.5rem 1.25rem",
                  fontSize: "0.9rem",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                }}
              >
                {isResetting && <Loader2 size={14} className="animate-spin" />}
                Confirm Reset
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Account Confirmation Modal */}
      {deleteModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="deleteModalTitle"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.65)",
            backdropFilter: "blur(2px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: "1rem",
          }}
        >
          <div
            style={{
              background: "var(--paper)",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--danger, #ef4444)",
              maxWidth: "480px",
              width: "100%",
              padding: "1.5rem",
              boxShadow: "0 10px 25px rgba(0, 0, 0, 0.3)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <AlertTriangle size={22} style={{ color: "var(--danger, #ef4444)" }} />
                <h3 id="deleteModalTitle" style={{ fontSize: "1.15rem", fontWeight: 600, margin: 0, color: "var(--danger, #ef4444)" }}>
                  Delete Account Permanently
                </h3>
              </div>
              <button
                type="button"
                aria-label="Close modal"
                onClick={() => !isDeleting && setDeleteModalOpen(false)}
                disabled={isDeleting}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)" }}
              >
                <X size={18} />
              </button>
            </div>

            <p style={{ fontSize: "0.9rem", color: "var(--muted)", lineHeight: 1.5, marginBottom: "1rem" }}>
              Warning: This action is permanent and cannot be undone. All your account information, comments, course progress, practice submissions, and avatars will be completely erased.
            </p>

            <div style={{ marginBottom: "1.25rem" }}>
              <label htmlFor="deleteConfirmInput" style={{ display: "block", fontSize: "0.85rem", fontWeight: 500, marginBottom: "0.4rem" }}>
                To confirm permanent deletion, type <strong style={{ color: "var(--danger, #ef4444)" }}>DELETE</strong>:
              </label>
              <input
                id="deleteConfirmInput"
                type="text"
                placeholder="DELETE"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                disabled={isDeleting}
                style={{
                  width: "100%",
                  padding: "0.6rem 0.85rem",
                  borderRadius: "var(--radius)",
                  border: "1px solid var(--danger, #ef4444)",
                  background: "var(--bg)",
                  color: "var(--ink)",
                  fontSize: "0.95rem",
                }}
              />
              {deleteError && (
                <div role="alert" style={{ color: "var(--danger, #ef4444)", fontSize: "0.8rem", marginTop: "0.4rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                  <AlertCircle size={14} />
                  <span>{deleteError}</span>
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setDeleteModalOpen(false)}
                disabled={isDeleting}
                style={{ padding: "0.5rem 1rem", fontSize: "0.9rem" }}
              >
                Cancel
              </button>
              <button
                id="confirmDeleteAccountBtn"
                type="button"
                className="btn btn-danger"
                onClick={handleDeleteAccount}
                disabled={isDeleting || deleteConfirmText.trim() !== "DELETE"}
                style={{
                  background: "var(--danger, #ef4444)",
                  color: "#ffffff",
                  border: "none",
                  padding: "0.5rem 1.25rem",
                  fontSize: "0.9rem",
                  borderRadius: "var(--radius)",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  cursor: deleteConfirmText.trim() === "DELETE" && !isDeleting ? "pointer" : "not-allowed",
                }}
              >
                {isDeleting && <Loader2 size={14} className="animate-spin" />}
                Permanently Delete Account
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

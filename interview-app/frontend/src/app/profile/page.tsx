"use client";

import React, { useState, useEffect, useRef } from "react";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { UserAvatar } from "@/components/UserAvatar";
import {
  validateAvatarFile,
  optimizeAvatarImage,
  MAX_AVATAR_BYTES,
} from "@/utils/avatar-validation";
import { User, Pencil, RefreshCw, CheckCircle, AlertCircle, Loader2 } from "lucide-react";

type UploadState = "idle" | "validating" | "preview_ready" | "uploading" | "success" | "error";

export default function ProfilePage() {
  const { user, refreshProfile } = useAuth();

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
    if (!user) {
      setStatusText("Not signed in.");
      setStatusType("info");
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
  }, [user]);

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

  const isBusy = isSaving || uploadState === "validating" || uploadState === "uploading";

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
    </main>
  );
}

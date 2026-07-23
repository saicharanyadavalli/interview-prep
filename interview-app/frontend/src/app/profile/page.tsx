"use client";

import React, { useState, useEffect, useRef } from "react";
import Image from "next/image";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { User, Pencil } from "lucide-react";

const AVATAR_MAX_BYTES = 512 * 1024;

function readImageDimensions(file: File): Promise<{ width: number; height: number; image: HTMLImageElement }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new window.Image();
    img.onload = () => {
      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      URL.revokeObjectURL(url);
      resolve({ width, height, image: img });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read image."));
    };
    img.src = url;
  });
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", quality);
  });
}

async function compressAvatarToLimit(file: File, maxBytes = AVATAR_MAX_BYTES): Promise<File> {
  if (!file || !file.type.startsWith("image/")) {
    throw new Error("Please choose a valid image file.");
  }

  if (file.size <= maxBytes) {
    return file;
  }

  const { width, height, image } = await readImageDimensions(file);
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("Image compression is not supported in this browser.");
  }

  let targetW = width;
  let targetH = height;
  const maxDim = 1400;
  if (Math.max(targetW, targetH) > maxDim) {
    const ratio = maxDim / Math.max(targetW, targetH);
    targetW = Math.max(1, Math.round(targetW * ratio));
    targetH = Math.max(1, Math.round(targetH * ratio));
  }

  for (let round = 0; round < 6; round += 1) {
    canvas.width = targetW;
    canvas.height = targetH;
    ctx.clearRect(0, 0, targetW, targetH);
    ctx.drawImage(image, 0, 0, targetW, targetH);

    for (const quality of [0.9, 0.82, 0.74, 0.66, 0.58, 0.5, 0.42]) {
      const blob = await canvasToBlob(canvas, quality);
      if (blob && blob.size <= maxBytes) {
        const base = (file.name || "avatar").replace(/\.[^.]+$/, "");
        return new File([blob], `${base}.jpg`, {
          type: "image/jpeg",
          lastModified: Date.now(),
        });
      }
    }

    targetW = Math.max(1, Math.round(targetW * 0.85));
    targetH = Math.max(1, Math.round(targetH * 0.85));
  }

  throw new Error("Could not compress image to 512KB. Try a smaller image.");
}

function buildAvatarFallback(name: string) {
  const trimmed = String(name || "").trim();
  const parts = trimmed.split(/\s+/).filter(Boolean);
  const initials = parts.length > 1
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : (parts[0] ? parts[0][0].toUpperCase() : "U");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="#0f766e"/><text x="48" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" fill="#ffffff">${initials}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export default function ProfilePage() {
  const { user } = useAuth();
  
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [statusText, setStatusText] = useState("Loading profile...");
  const [isBusy, setIsBusy] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let mounted = true;
    if (!user) {
      setStatusText("Not signed in.");
      return;
    }
    
    setStatusText("Loading profile...");
    
    const loadData = async () => {
      try {
        const cached = API.getCachedProfile ? API.getCachedProfile(12 * 60 * 60 * 1000) : null;
        if (cached) {
          if (mounted) {
            setName(cached.name || "");
            setUsername(cached.username || "");
            setPhone(cached.phone || "");
            setEmail(cached.email || user.email || "");
            setAvatarUrl(cached.avatar_url || "");
            setStatusText("Profile loaded.");
          }
        }
        
        const profile = await API.getMyProfile({ preferCache: false });
        if (mounted) {
          setName(profile.name || "");
          setUsername(profile.username || "");
          setPhone(profile.phone || "");
          setEmail(profile.email || user.email || "");
          setAvatarUrl(profile.avatar_url || "");
          setStatusText("Profile loaded.");
        }
      } catch (err: any) {
        if (mounted) setStatusText(`Could not load profile: ${err.message}`);
      }
    };
    
    loadData();
    
    return () => { mounted = false; };
  }, [user]);

  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const digitsOnly = String(e.target.value || "").replace(/\D+/g, "").slice(0, 10);
    setPhone(digitsOnly);
  };
  
  const handlePhonePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = (e.clipboardData.getData("text") || "").replace(/\D+/g, "").slice(0, 10);
    setPhone(pasted);
  };

  const handleSave = async () => {
    setIsBusy(true);
    setStatusText("Saving profile...");
    try {
      const updated = await API.updateMyProfile({
        name: name.trim(),
        username: username.trim().toLowerCase(),
        phone: phone.trim(),
        avatar_url: avatarUrl.trim(),
      });
      setName(updated.name || "");
      setUsername(updated.username || "");
      setPhone(updated.phone || "");
      setEmail(updated.email || email);
      setAvatarUrl(updated.avatar_url || "");
      setStatusText("Profile saved.");
    } catch (err: any) {
      setStatusText(`Save failed: ${err.message}`);
    } finally {
      setIsBusy(false);
    }
  };

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setIsBusy(true);
    setStatusText("Compressing image...");
    
    try {
      const compressed = await compressAvatarToLimit(file, AVATAR_MAX_BYTES);
      setStatusText(`Uploading image (${Math.round(compressed.size / 1024)}KB)...`);
      
      const data = await API.uploadProfileAvatar(compressed);
      setAvatarUrl(data.avatar_url || "");
      
      // Update cache
      if (API.setCachedProfile) {
        API.setCachedProfile({
          ...(API.getCachedProfile ? API.getCachedProfile(0) : {}),
          name: name.trim(),
          username: username.trim().toLowerCase(),
          email: email.trim(),
          phone: phone.trim(),
          avatar_url: data.avatar_url || "",
        });
      }
      
      setStatusText("Avatar uploaded and saved.");
    } catch (err: any) {
      setStatusText(`Avatar upload failed: ${err.message}`);
    } finally {
      setIsBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <main className="main-content">
      <div className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <User size={28} className="text-teal" /> Profile
        </h1>
      </div>

      <section className="card-flat section" style={{ padding: '1.5rem', background: 'var(--paper)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)' }}>
        <div className="card-header" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1.1rem' }}>Account Details</h3>
        </div>
        
        <div className="form-row section" style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
          <div className="control-group" style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label htmlFor="profileName" style={{ fontWeight: 500 }}>Full Name</label>
            <input 
              id="profileName" 
              type="text" 
              placeholder="Enter full name" 
              value={name}
              onChange={e => setName(e.target.value)}
              style={{ padding: '0.5rem 1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)' }}
            />
          </div>
          <div className="control-group" style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label htmlFor="profileUsername" style={{ fontWeight: 500 }}>Username</label>
            <input 
              id="profileUsername" 
              type="text" 
              placeholder="Enter username" 
              value={username}
              onChange={e => setUsername(e.target.value)}
              style={{ padding: '0.5rem 1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)' }}
            />
          </div>
          <div className="control-group" style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label htmlFor="profilePhone" style={{ fontWeight: 500 }}>Phone Number</label>
            <input 
              id="profilePhone" 
              type="text" 
              inputMode="numeric" 
              autoComplete="tel-national" 
              pattern="[0-9]{10}" 
              maxLength={10} 
              placeholder="Enter 10-digit phone number"
              value={phone}
              onChange={handlePhoneChange}
              onPaste={handlePhonePaste}
              style={{ padding: '0.5rem 1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)' }}
            />
          </div>
        </div>

        <div className="control-group section" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1.5rem' }}>
          <label htmlFor="profileEmail" style={{ fontWeight: 500 }}>Email</label>
          <input 
            id="profileEmail" 
            type="email" 
            disabled 
            value={email}
            style={{ padding: '0.5rem 1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--sidebar-bg)', color: 'var(--muted)', cursor: 'not-allowed' }}
          />
        </div>

        <div className="control-group section" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1.5rem' }}>
          <label style={{ fontWeight: 500 }}>Profile Picture</label>
          <div className="profile-avatar-editor" style={{ position: 'relative', width: '96px', height: '96px', borderRadius: '50%', background: 'var(--sidebar-bg)' }}>
            <Image 
              id="profileAvatarPreview" 
              className="profile-avatar-preview" 
              src={avatarUrl || buildAvatarFallback(name)} 
              onError={(e) => { e.currentTarget.srcset = buildAvatarFallback(name); }}
              alt="Profile picture" 
              width={96}
              height={96}
              style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }}
            />
            <button 
              id="profileAvatarEditBtn" 
              className="profile-avatar-edit-btn" 
              type="button" 
              aria-label="Upload profile picture"
              onClick={() => fileInputRef.current?.click()}
              disabled={isBusy}
              style={{ position: 'absolute', bottom: 0, right: 0, background: 'var(--teal)', color: 'white', border: 'none', borderRadius: '50%', width: '28px', height: '28px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: '12px' }}
            >
              <Pencil size={12} />
            </button>
            <input 
              id="profileAvatarFile" 
              className="profile-avatar-file-input" 
              type="file" 
              accept="image/*" 
              aria-label="Choose profile picture"
              ref={fileInputRef}
              onChange={handleAvatarChange}
              style={{ display: 'none' }}
            />
          </div>
          <p className="text-sm text-muted" style={{ fontSize: '0.85rem' }}>Click the pencil icon to upload a profile image. It is automatically compressed to 512KB max.</p>
        </div>

        <div className="status-bar section" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2rem', padding: '1rem', background: 'var(--bg)', borderRadius: 'var(--radius)' }}>
          <span id="profileStatus" className="status-text text-muted" style={{ fontSize: '0.9rem' }}>{statusText}</span>
          <div className="status-right">
            <button id="saveProfileBtn" className="btn btn-primary" type="button" onClick={handleSave} disabled={isBusy || !user}>Save Profile</button>
          </div>
        </div>
      </section>
    </main>
  );
}

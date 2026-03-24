/**
 * profile.js - Profile page logic.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("profile", { requireLogin: true });
  initProfilePage();
});

const AVATAR_MAX_BYTES = 512 * 1024;

function readImageDimensions(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
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

function canvasToBlob(canvas, quality) {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", quality);
  });
}

async function compressAvatarToLimit(file, maxBytes = AVATAR_MAX_BYTES) {
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

function buildAvatarFallback(name) {
  const trimmed = String(name || "").trim();
  const parts = trimmed.split(/\s+/).filter(Boolean);
  const initials = parts.length > 1
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : (parts[0] ? parts[0][0].toUpperCase() : "U");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="#0f766e"/><text x="48" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" fill="#ffffff">${initials}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

async function initProfilePage() {
  const nameInput = document.getElementById("profileName");
  const phoneInput = document.getElementById("profilePhone");
  const emailInput = document.getElementById("profileEmail");
  const avatarPreview = document.getElementById("profileAvatarPreview");
  const avatarEditBtn = document.getElementById("profileAvatarEditBtn");
  const avatarFileInput = document.getElementById("profileAvatarFile");
  const saveBtn = document.getElementById("saveProfileBtn");
  const statusEl = document.getElementById("profileStatus");
  let currentAvatarUrl = "";

  function setStatus(message) {
    if (statusEl) statusEl.textContent = message;
  }

  function syncSidebarAvatar() {
    const sidebarAvatar = document.querySelector(".sidebar-avatar");
    const displayName = nameInput ? nameInput.value.trim() : "";
    const avatarUrl = String(currentAvatarUrl || "").trim();
    if (!sidebarAvatar) return;

    const fallback = buildAvatarFallback(displayName);
    sidebarAvatar.src = avatarUrl || fallback;
    sidebarAvatar.onerror = () => {
      sidebarAvatar.onerror = null;
      sidebarAvatar.src = fallback;
    };
  }

  async function loadProfile() {
    setStatus("Loading profile...");
    try {
      const cached = API.getCachedProfile ? API.getCachedProfile(12 * 60 * 60 * 1000) : null;
      if (cached) {
        if (nameInput) nameInput.value = cached.name || "";
        if (phoneInput) phoneInput.value = cached.phone || "";
        if (emailInput) emailInput.value = cached.email || "";
        currentAvatarUrl = cached.avatar_url || "";
        syncProfileAvatarPreview();
        syncSidebarAvatar();
        setStatus("Profile loaded.");
      }

      const profile = await API.getMyProfile({ preferCache: false });
      if (nameInput) nameInput.value = profile.name || "";
      if (phoneInput) phoneInput.value = profile.phone || "";
      if (emailInput) emailInput.value = profile.email || "";
      currentAvatarUrl = profile.avatar_url || "";
      syncProfileAvatarPreview();
      syncSidebarAvatar();
      setStatus("Profile loaded.");
    } catch (err) {
      setStatus(`Could not load profile: ${err.message}`);
    }
  }

  function syncProfileAvatarPreview() {
    if (!avatarPreview) return;
    const displayName = nameInput ? nameInput.value.trim() : "";
    const fallback = buildAvatarFallback(displayName);
    avatarPreview.src = (currentAvatarUrl || "").trim() || fallback;
    avatarPreview.onerror = () => {
      avatarPreview.onerror = null;
      avatarPreview.src = fallback;
    };
  }

  async function saveProfile() {
    if (saveBtn) saveBtn.disabled = true;
    setStatus("Saving profile...");
    try {
      const updated = await API.updateMyProfile({
        name: nameInput ? nameInput.value.trim() : "",
        phone: phoneInput ? phoneInput.value.trim() : "",
        avatar_url: String(currentAvatarUrl || "").trim(),
      });

      if (nameInput) nameInput.value = updated.name || "";
      if (phoneInput) phoneInput.value = updated.phone || "";
      if (emailInput) emailInput.value = updated.email || "";
      currentAvatarUrl = updated.avatar_url || "";
      syncProfileAvatarPreview();
      syncSidebarAvatar();

      const nameEl = document.querySelector(".sidebar-user-name");
      if (nameEl) nameEl.textContent = updated.name || "User";

      setStatus("Profile saved.");
    } catch (err) {
      setStatus(`Save failed: ${err.message}`);
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async function uploadAvatarToCloudinary() {
    if (!avatarFileInput || !avatarFileInput.files || !avatarFileInput.files.length) {
      setStatus("Choose an image file first.");
      return;
    }

    const file = avatarFileInput.files[0];
    if (avatarEditBtn) avatarEditBtn.disabled = true;
    setStatus("Compressing image...");

    try {
      const compressed = await compressAvatarToLimit(file, AVATAR_MAX_BYTES);
      setStatus(`Uploading image (${Math.round(compressed.size / 1024)}KB)...`);

      const data = await API.uploadProfileAvatar(compressed);
      currentAvatarUrl = data.avatar_url || "";
      syncProfileAvatarPreview();
      syncSidebarAvatar();
      const nameEl = document.querySelector(".sidebar-user-name");
      const emailEl = document.querySelector(".sidebar-user-email");
      API.setCachedProfile({
        ...(API.getCachedProfile(0) || {}),
        name: nameInput ? nameInput.value.trim() : (nameEl ? nameEl.textContent : ""),
        email: emailInput ? emailInput.value.trim() : (emailEl ? emailEl.textContent : ""),
        phone: phoneInput ? phoneInput.value.trim() : "",
        avatar_url: currentAvatarUrl,
      });

      setStatus("Avatar uploaded and saved.");
      avatarFileInput.value = "";
    } catch (err) {
      setStatus(`Avatar upload failed: ${err.message}`);
    } finally {
      if (avatarEditBtn) avatarEditBtn.disabled = false;
    }
  }

  if (nameInput) {
    nameInput.addEventListener("input", () => {
      syncProfileAvatarPreview();
      syncSidebarAvatar();
    });
  }

  if (phoneInput) {
    phoneInput.addEventListener("input", () => {
      const digitsOnly = String(phoneInput.value || "").replace(/\D+/g, "").slice(0, 10);
      if (phoneInput.value !== digitsOnly) {
        phoneInput.value = digitsOnly;
      }
    });

    phoneInput.addEventListener("paste", (event) => {
      event.preventDefault();
      const pasted = (event.clipboardData?.getData("text") || "").replace(/\D+/g, "").slice(0, 10);
      phoneInput.value = pasted;
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", saveProfile);
  }

  if (avatarEditBtn && avatarFileInput) {
    avatarEditBtn.addEventListener("click", () => avatarFileInput.click());
    avatarFileInput.addEventListener("change", uploadAvatarToCloudinary);
  }

  await loadProfile();
}

/**
 * sidebar.js — Renders the sidebar navigation and handles mobile toggle.
 *
 * Call `initSidebar(activePage, { requireLogin: false })` from each page.
 * activePage should be one of: "dashboard", "practice", "revisit", "progress", "questions"
 * If requireLogin is true, unauthenticated users are redirected to index.html.
 */

const NAV_ITEMS = [
  { id: "dashboard",  label: "Dashboard",       icon: "📊", href: "dashboard.html" },
  { id: "questions",  label: "All Questions",   icon: "📋", href: "questions.html" },
  { id: "profile",    label: "Profile",         icon: "👤", href: "profile.html"   },
  { id: "revisit",    label: "Revisit Queue",   icon: "🔄", href: "revisit.html"   },
  { id: "progress",   label: "Progress",        icon: "📈", href: "progress.html"  },
];

function initialsFromName(name) {
  const text = String(name || "").trim();
  if (!text) return "U";
  const parts = text.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function buildAvatarDataUri(name) {
  const initials = initialsFromName(name);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="#0f766e"/><text x="48" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" fill="#ffffff">${initials}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/**
 * Initialize the sidebar, user info, and mobile toggling.
 * @param {string} activePage — the current page ID
 * @param {object} options — { requireLogin: boolean }
 */
async function initSidebar(activePage, options = {}) {
  const requireLogin = options.requireLogin !== undefined ? options.requireLogin : false;
  const sidebar = document.getElementById("sidebar");
  const toggle = document.getElementById("sidebarToggle");
  const overlay = document.getElementById("sidebarOverlay");

  if (!sidebar) return;

  // Build nav links
  const navContainer = sidebar.querySelector(".sidebar-nav");
  if (navContainer) {
    navContainer.innerHTML = "";
    NAV_ITEMS.forEach((item) => {
      const a = document.createElement("a");
      a.href = item.href;
      a.className = "sidebar-link" + (item.id === activePage ? " active" : "");
      a.innerHTML = `<span class="nav-icon">${item.icon}</span> ${item.label}`;
      navContainer.appendChild(a);
    });
  }

  // Auth — either hard redirect or soft fill
  let user = null;
  if (requireLogin) {
    user = await requireAuth();
  } else {
    user = await tryGetUser();
  }

  const avatarEl = sidebar.querySelector(".sidebar-avatar");
  const nameEl = sidebar.querySelector(".sidebar-user-name");
  const emailEl = sidebar.querySelector(".sidebar-user-email");

  // Default guest fallback to avoid broken avatar icon.
  if (avatarEl) {
    avatarEl.src = buildAvatarDataUri("User");
    avatarEl.onerror = () => {
      avatarEl.onerror = null;
      avatarEl.src = buildAvatarDataUri("User");
    };
  }

  // Populate user info if available
  if (user) {
    const meta = getUserMeta(user);

    // Prefer client cache for instant page transitions.
    let profileData = API.getCachedProfile ? API.getCachedProfile(12 * 60 * 60 * 1000) : null;
    if (!profileData) {
      try {
        profileData = await API.getMyProfile({ preferCache: false });
      } catch (_) {
        profileData = null;
      }
    }

    const displayName = (profileData && profileData.name) || meta.name || "User";
    const displayEmail = (profileData && profileData.email) || meta.email || "";
    const avatarUrl = (profileData && profileData.avatar_url) || meta.avatar || "";

    if (nameEl) nameEl.textContent = displayName;
    if (emailEl) emailEl.textContent = displayEmail;
    if (avatarEl) {
      const fallback = buildAvatarDataUri(displayName);
      avatarEl.src = avatarUrl || fallback;
      avatarEl.onerror = () => {
        avatarEl.onerror = null;
        avatarEl.src = fallback;
      };
    }
  }

  // Show/hide login/sign-out buttons based on auth state
  const signOutBtn = document.getElementById("signOutBtn");
  const loginBtn = document.getElementById("loginBtn");

  if (user) {
    if (signOutBtn) signOutBtn.classList.remove("hidden");
    if (loginBtn) loginBtn.classList.add("hidden");
  } else {
    if (signOutBtn) signOutBtn.classList.add("hidden");
    if (loginBtn) loginBtn.classList.remove("hidden");
  }

  // Theme toggle
  const themeBtn = document.getElementById("themeToggleBtn");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const current = document.body.getAttribute("data-theme");
      const next = current === "dark" ? "light" : "dark";
      document.body.setAttribute("data-theme", next);
      themeBtn.textContent = next === "dark" ? "☀️" : "🌙";
      localStorage.setItem("theme", next);
    });
  }

  // Sign out
  if (signOutBtn) {
    signOutBtn.addEventListener("click", () => signOut());
  }

  // Login button
  if (loginBtn) {
    loginBtn.addEventListener("click", () => {
      window.location.href = "index.html";
    });
  }

  // Mobile sidebar toggle
  if (toggle) {
    toggle.addEventListener("click", () => {
      sidebar.classList.toggle("open");
      if (overlay) overlay.classList.toggle("open");
    });
  }
  if (overlay) {
    overlay.addEventListener("click", () => {
      sidebar.classList.remove("open");
      overlay.classList.remove("open");
    });
  }

  // Load saved theme
  const savedTheme = localStorage.getItem("theme") || "dark";
  document.body.setAttribute("data-theme", savedTheme);
  if (themeBtn) {
    themeBtn.textContent = savedTheme === "dark" ? "☀️" : "🌙";
  }

  return user;
}

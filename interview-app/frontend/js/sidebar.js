/**
 * sidebar.js — Renders the sidebar navigation and handles mobile toggle.
 *
 * Call `initSidebar(activePage, { requireLogin: false })` from each page.
 * activePage should be one of: "dashboard", "system-design", "practice", "revisit", "progress", "questions", "profile"
 * If requireLogin is true, unauthenticated users are redirected to index.html.
 */

const NAV_ITEMS = [
  { id: "dashboard",  label: "Dashboard",       icon: "📊", href: "dashboard.html" },
  { id: "system-design", label: "System Design", icon: "🧠", href: "system-design.html" },
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
  const themeBtn = document.getElementById("themeToggleBtn");
  const COLLAPSIBLE_BREAKPOINT = 1024;

  if (!sidebar) return;

  let isCollapsibleMode = false;
  let mobileSidebarOpen = false;
  let lastCollapsibleMode = null;

  const normalizeTheme = (theme) => (theme === "light" ? "light" : "dark");

  const applyTheme = (theme) => {
    const nextTheme = normalizeTheme(theme);
    document.body.setAttribute("data-theme", nextTheme);
    if (themeBtn) {
      const darkActive = nextTheme === "dark";
      themeBtn.textContent = darkActive ? "☀️" : "🌙";
      themeBtn.setAttribute("title", darkActive ? "Switch to light mode" : "Switch to dark mode");
      themeBtn.setAttribute("aria-label", darkActive ? "Switch to light mode" : "Switch to dark mode");
      themeBtn.setAttribute("aria-pressed", darkActive ? "true" : "false");
    }
  };

  const setSidebarOpen = (isOpen) => {
    // Keep sidebar pinned open on larger screens and drawer-style on smaller screens.
    const open = isCollapsibleMode ? Boolean(isOpen) : true;
    mobileSidebarOpen = open;
    sidebar.classList.toggle("open", open);
    if (overlay) {
      overlay.classList.toggle("open", isCollapsibleMode && open);
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }
  };

  const applySidebarMode = () => {
    const nextCollapsibleMode = window.innerWidth <= COLLAPSIBLE_BREAKPOINT;
    if (lastCollapsibleMode !== nextCollapsibleMode && nextCollapsibleMode) {
      mobileSidebarOpen = false;
    }
    isCollapsibleMode = nextCollapsibleMode;
    lastCollapsibleMode = nextCollapsibleMode;
    document.body.classList.toggle("has-collapsible-sidebar", isCollapsibleMode);
    setSidebarOpen(isCollapsibleMode ? mobileSidebarOpen : true);
  };

  // Bind core interactions before async auth/profile calls so toggle always works.
  if (toggle && !toggle.dataset.sidebarBound) {
    toggle.dataset.sidebarBound = "1";
    toggle.addEventListener("click", () => {
      if (!isCollapsibleMode) return;
      const currentlyOpen = sidebar.classList.contains("open");
      setSidebarOpen(!currentlyOpen);
    });
  }
  if (overlay && !overlay.dataset.sidebarBound) {
    overlay.dataset.sidebarBound = "1";
    overlay.addEventListener("click", () => {
      setSidebarOpen(false);
    });
  }
  if (!document.body.dataset.sidebarEscBound) {
    document.body.dataset.sidebarEscBound = "1";
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        setSidebarOpen(false);
      }
    });
  }
  if (!window.__ippSidebarResizeBound) {
    window.__ippSidebarResizeBound = true;
    window.addEventListener("resize", () => {
      applySidebarMode();
    });
  }

  // Load and apply saved theme immediately for visible mode consistency.
  const savedTheme = normalizeTheme(localStorage.getItem("theme") || document.body.getAttribute("data-theme") || "dark");
  applyTheme(savedTheme);

  if (themeBtn && !themeBtn.dataset.themeBound) {
    themeBtn.dataset.themeBound = "1";
    themeBtn.addEventListener("click", () => {
      const current = normalizeTheme(document.body.getAttribute("data-theme"));
      const next = current === "dark" ? "light" : "dark";
      applyTheme(next);
      localStorage.setItem("theme", next);
    });
  }

  applySidebarMode();

  // Keep drawer closed by default in collapsible mode.
  if (isCollapsibleMode) {
    setSidebarOpen(false);
  }

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
  try {
    if (requireLogin) {
      user = await requireAuth();
    } else {
      user = await tryGetUser();
    }
  } catch (_) {
    user = null;
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

  if (navContainer) {
    navContainer.querySelectorAll(".sidebar-link").forEach((link) => {
      link.addEventListener("click", () => {
        if (isCollapsibleMode) {
          setSidebarOpen(false);
        }
      });
    });
  }

  return user;
}

/**
 * dashboard.js — Dashboard page logic.
 *
 * Fetches progress stats and recent activity from the backend,
 * then renders stat cards, recent questions, and revisit queue preview.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("dashboard", { requireLogin: true });

  const { session } = await getSession();
  if (session) {
    await syncSessionWithBackend(session.access_token);
  }

  loadDashboardData();
});

async function loadDashboardData() {
  const statsGrid = document.getElementById("statsGrid");
  const recentList = document.getElementById("recentList");
  const revisitPreview = document.getElementById("revisitPreview");
  const systemDesignFill = document.getElementById("dashboardSystemDesignFill");
  const systemDesignText = document.getElementById("dashboardSystemDesignText");

  const [progressResult, revisitResult, systemDesignResult] = await Promise.allSettled([
    API.getUserProgress(),
    API.getRevisitQueue(),
    API.getSystemDesignProgress(),
  ]);

  if (progressResult.status === "fulfilled") {
    const progress = progressResult.value;
    renderStats(statsGrid, progress.stats);
    renderRecentList(recentList, progress.recent);
  } else {
    renderStats(statsGrid, { total_attempted: 0, revisit_count: 0 });
    if (recentList) {
      recentList.innerHTML = '<p class="track-empty">No recent questions yet. Start practicing!</p>';
    }
  }

  if (revisitResult.status === "fulfilled") {
    const revisit = revisitResult.value;
    renderRevisitPreview(revisitPreview, revisit.items);
  } else {
    if (revisitPreview) {
      revisitPreview.innerHTML = '<p class="track-empty">No revisit questions yet.</p>';
    }
  }

  const systemDesign = systemDesignResult && systemDesignResult.status === "fulfilled"
    ? systemDesignResult.value
    : null;
  renderSystemDesignProgress(systemDesignFill, systemDesignText, systemDesign);
}

function renderStats(container, stats) {
  if (!container) return;
  container.innerHTML = `
    <div class="stat-card attempted animate-slide" style="animation-delay:0ms">
      <p class="stat-label">Total Attempted</p>
      <p class="stat-value">${stats.total_attempted}</p>
    </div>
    <div class="stat-card revisit animate-slide" style="animation-delay:80ms">
      <p class="stat-label">Revisit</p>
      <p class="stat-value">${stats.revisit_count}</p>
    </div>
  `;
}

function renderRecentList(container, recent) {
  if (!container) return;
  if (!recent || recent.length === 0) {
    container.innerHTML = '<p class="track-empty">No recent questions yet. Start practicing!</p>';
    return;
  }

  container.innerHTML = "";
  recent.slice(0, 8).forEach((entry) => {
    const item = document.createElement("div");
    item.className = "track-item";
    const isSolved = Boolean(entry.is_solved);
    const revisit = Boolean(entry.revisit);
    let statusLabel = "Not Solved";
    let color = "var(--muted)";

    if (revisit) {
      statusLabel = isSolved ? "Solved + Revisit" : "Revisit";
      color = "var(--amber)";
    } else if (isSolved) {
      statusLabel = "Solved";
      color = "var(--green)";
    }
    item.innerHTML = `
      <div class="track-item-main">
        <p class="track-title">${escapeHtml(entry.question_title || entry.question_id)}</p>
        <p class="track-meta">${escapeHtml(entry.company)} · ${escapeHtml(entry.difficulty)} · <span style="color:${color};font-weight:600">${statusLabel}</span></p>
      </div>
      <a href="solve.html?qnum=${encodeURIComponent(entry.qnum || "")}" class="btn btn-sm">Practice</a>
    `;
    container.appendChild(item);
  });
}

function renderRevisitPreview(container, items) {
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="track-empty">No questions in your revisit queue.</p>';
    return;
  }

  container.innerHTML = "";
  items.slice(0, 5).forEach((entry) => {
    const item = document.createElement("div");
    item.className = "track-item";
    item.innerHTML = `
      <div class="track-item-main">
        <p class="track-title">${escapeHtml(entry.question_title || `Question #${entry.qnum || ""}`)}</p>
        <p class="track-meta">${escapeHtml(entry.company)} · ${escapeHtml(entry.difficulty)}</p>
      </div>
      <a href="solve.html?qnum=${encodeURIComponent(entry.qnum || "")}" class="btn btn-sm">Practice</a>
    `;
    container.appendChild(item);
  });

  if (items.length > 5) {
    const more = document.createElement("a");
    more.href = "revisit.html";
    more.className = "text-teal text-sm";
    more.style.marginTop = "0.5rem";
    more.style.display = "block";
    more.textContent = `View all ${items.length} items →`;
    container.appendChild(more);
  }
}

function renderSystemDesignProgress(fillEl, textEl, data) {
  if (!fillEl || !textEl) return;

  const total = Number((data && data.total_steps) || 30);
  const completed = Number((data && data.completed_steps) || 0);
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

  fillEl.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  textEl.textContent = `${completed} / ${total} completed`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

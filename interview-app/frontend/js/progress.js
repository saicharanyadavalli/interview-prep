/**
 * progress.js — Progress page logic.
 *
 * Fetches user progress stats and recent history from the backend,
 * then renders stat cards and a history timeline.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("progress", { requireLogin: true });
  loadProgress();
});

async function loadProgress() {
  const statsGrid = document.getElementById("statsGrid");
  const historyList = document.getElementById("historyList");

  if (statsGrid) statsGrid.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading...</p>';

  try {
    const data = await API.getUserProgress();
    renderProgressStats(statsGrid, data.stats);
    renderHistory(historyList, data.recent);
  } catch (err) {
    renderProgressStats(statsGrid, {
      total_attempted: 0, revisit_count: 0,
    });
    if (historyList) {
      historyList.innerHTML = `
        <div class="empty-state">
          <p class="empty-icon">📊</p>
          <p>No progress data yet.</p>
          <p class="text-sm text-muted">${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }
}

function renderProgressStats(container, stats) {
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

function renderHistory(container, recent) {
  if (!container) return;
  if (!recent || recent.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">📝</p>
        <p>No practice history yet. Start practicing to see your progress!</p>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  recent.forEach((entry, idx) => {
    const item = document.createElement("div");
    item.className = "track-item animate-slide";
    item.style.animationDelay = `${idx * 50}ms`;

    const rawStatus = String(entry.status || "").toLowerCase();
    let color = "var(--muted)";
    const statusEmoji = { strong: "✅", good: "✅", revisit: "🔄", skip: "❌" };
    const emoji = statusEmoji[rawStatus] || "📌";
    let statusLabel = "Not Solved";
    if (rawStatus === "revisit") {
      statusLabel = "Solved + Revisit";
      color = "var(--amber)";
    } else if (rawStatus === "good" || rawStatus === "strong") {
      statusLabel = "Solved";
      color = "var(--green)";
    }

    item.innerHTML = `
      <div class="track-item-main">
        <p class="track-title">${emoji} ${escapeHtml(entry.question_title || entry.question_id)}</p>
        <p class="track-meta">
          ${escapeHtml(entry.company)} · ${escapeHtml(entry.difficulty)} ·
          <span style="color:${color};font-weight:600">${statusLabel}</span>
          ${entry.updated_at ? " · " + formatDate(entry.updated_at) : ""}
        </p>
      </div>
      <a href="solve.html?qnum=${encodeURIComponent(entry.qnum || "")}" class="btn btn-sm">Practice</a>
    `;
    container.appendChild(item);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return dateStr;
  }
}

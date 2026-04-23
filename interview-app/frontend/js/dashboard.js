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
  const learningTracksList = document.getElementById("dashboardLearningTracksList");

  const [progressResult, revisitResult, learningTracksResult] = await Promise.allSettled([
    API.getUserProgress(),
    API.getRevisitQueue(),
    API.getLearningTracks(),
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

  const tracks = learningTracksResult && learningTracksResult.status === "fulfilled"
    ? (Array.isArray(learningTracksResult.value && learningTracksResult.value.tracks)
      ? learningTracksResult.value.tracks
      : [])
    : (Array.isArray(window.LEARNING_TRACKS) ? window.LEARNING_TRACKS : []);

  await renderLearningTracksProgress(learningTracksList, tracks);
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

async function renderLearningTracksProgress(container, tracks) {
  if (!container) return;

  const safeTracks = Array.isArray(tracks) ? tracks : [];
  if (!safeTracks.length) {
    container.innerHTML = '<p class="track-empty">No learning tracks available yet.</p>';
    return;
  }

  const progressEntries = await Promise.all(
    safeTracks.map(async (track) => {
      const trackId = String((track && track.track_id) || "").trim();
      if (!trackId) return null;

      try {
        const data = await API.getLearningTrackProgress(trackId);
        return { track, data };
      } catch (_) {
        return { track, data: null };
      }
    })
  );

  container.innerHTML = progressEntries
    .filter(Boolean)
    .map(({ track, data }) => {
      const trackId = String((track && track.track_id) || "").trim();
      const localMeta = typeof getLearningTrackById === "function" ? getLearningTrackById(trackId) : null;
      const icon = String((localMeta && localMeta.icon) || track.icon || "📘");
      const name = escapeHtml(String((track && track.display_name) || (localMeta && localMeta.display_name) || "Learning Track"));
      const href = escapeHtml(String((localMeta && localMeta.course_href) || track.course_href || "#"));
      const total = Number((data && data.total_steps) || track.step_count || 0);
      const completed = Number((data && data.completed_steps) || 0);
      const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

      return `
        <article class="dashboard-track-item">
          <div class="dashboard-track-row">
            <p><strong>${icon} ${name}</strong></p>
            <a class="btn btn-sm" href="${href}">Open Course</a>
          </div>
          <div class="progress-wrap dashboard-track-progress">
            <div class="progress-fill" style="width:${Math.max(0, Math.min(100, percent))}%"></div>
          </div>
          <p class="text-sm text-muted dashboard-track-text">${completed} / ${total} completed</p>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

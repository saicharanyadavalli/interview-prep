/**
 * revisit.js — Revisit Queue page logic.
 *
 * Fetches the user's revisit queue from the backend and renders
 * a list with practice-again and remove actions.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("revisit", { requireLogin: true });
  loadRevisitQueue();
});

async function loadRevisitQueue() {
  const container = document.getElementById("revisitList");
  const countBadge = document.getElementById("revisitCount");
  if (!container) return;

  container.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading revisit queue...</p>';

  try {
    const data = await API.getRevisitQueue();
    const items = data.items || [];

    if (countBadge) countBadge.textContent = items.length;

    if (items.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p class="empty-icon">📋</p>
          <p>Your revisit queue is empty.</p>
          <p class="text-sm text-muted">Mark questions as "Revisit" during practice to add them here.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = "";
    items.forEach((entry, idx) => {
      const item = document.createElement("div");
      item.className = "track-item";
      item.innerHTML = `
        <div class="track-item-main">
          <p class="track-title">#${idx + 1} ${escapeHtml(entry.question_title || `Question #${entry.qnum || ""}`)}</p>
          <p class="track-meta">${escapeHtml(entry.company)} · ${escapeHtml(entry.difficulty)} · Added ${formatDate(entry.added_at)}</p>
        </div>
        <div class="track-actions">
          <a href="solve.html?qnum=${encodeURIComponent(entry.qnum || "")}" class="btn btn-sm btn-primary">Practice</a>
          <button class="btn btn-sm btn-danger" data-qnum="${escapeAttr(entry.qnum)}">Remove</button>
        </div>
      `;
      container.appendChild(item);
    });

    // Attach remove handlers
    container.querySelectorAll("[data-qnum]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const qnum = Number(btn.dataset.qnum || 0);
        btn.disabled = true;
        btn.textContent = "...";
        try {
          await API.removeFromRevisit(qnum);
          loadRevisitQueue(); // Reload
        } catch (err) {
          alert("Failed to remove: " + err.message);
          btn.disabled = false;
          btn.textContent = "Remove";
        }
      });
    });
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">⚠️</p>
        <p>Could not load revisit queue.</p>
        <p class="text-sm text-muted">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function escapeAttr(text) {
  return String(text || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return dateStr;
  }
}

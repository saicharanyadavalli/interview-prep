/**
 * revisit.js - Revisit queue page logic with upgraded visuals.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("revisit", { requireLogin: true });
  loadRevisitQueue();
});

async function loadRevisitQueue() {
  const container = document.getElementById("revisitList");
  const countBadge = document.getElementById("revisitCount");
  const totalStat = document.getElementById("revisitTotalStat");
  const easyStat = document.getElementById("revisitEasyStat");
  const mediumStat = document.getElementById("revisitMediumStat");
  const hardStat = document.getElementById("revisitHardStat");

  if (!container) return;

  container.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading revisit queue...</p>';

  try {
    const data = await API.getRevisitQueue();
    const items = Array.isArray(data && data.items) ? data.items : [];

    const summary = summarizeQueue(items);
    if (countBadge) countBadge.textContent = String(summary.total);
    if (totalStat) totalStat.textContent = String(summary.total);
    if (easyStat) easyStat.textContent = String(summary.easy);
    if (mediumStat) mediumStat.textContent = String(summary.medium);
    if (hardStat) hardStat.textContent = String(summary.hard);

    if (!items.length) {
      container.innerHTML = `
        <div class="empty-state">
          <p class="empty-icon">📋</p>
          <p>Your revisit queue is empty.</p>
          <p class="text-sm text-muted">Mark questions as Revisit while practicing to bring them here.</p>
        </div>
      `;
      return;
    }

    renderRevisitItems(container, items);
    bindRemoveHandlers(container);
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

function summarizeQueue(items) {
  const summary = {
    total: 0,
    easy: 0,
    medium: 0,
    hard: 0,
  };

  (Array.isArray(items) ? items : []).forEach((entry) => {
    summary.total += 1;
    const difficulty = normalizeDifficulty(entry && entry.difficulty);
    if (difficulty === "easy") summary.easy += 1;
    if (difficulty === "medium") summary.medium += 1;
    if (difficulty === "hard") summary.hard += 1;
  });

  return summary;
}

function renderRevisitItems(container, items) {
  container.innerHTML = items
    .map((entry, index) => {
      const difficulty = normalizeDifficulty(entry && entry.difficulty);
      const difficultyLabel = titleCase(difficulty || "unknown");

      return `
        <article class="revisit-v3-item diff-${difficulty}">
          <div class="revisit-v3-item-head">
            <h3>${index + 1}. ${escapeHtml(entry.question_title || `Question #${entry.qnum || ""}`)}</h3>
            <span class="pill revisit-v3-diff-pill ${difficulty}">${escapeHtml(difficultyLabel)}</span>
          </div>

          <p class="revisit-v3-item-meta">
            ${escapeHtml(entry.company || "Unknown Company")}
            ${entry.added_at ? ` • Added ${formatDate(entry.added_at)}` : ""}
          </p>

          <div class="revisit-v3-actions">
            <a href="solve.html?qnum=${encodeURIComponent(entry.qnum || "")}" class="btn btn-sm btn-primary">Practice Now</a>
            <button class="btn btn-sm btn-danger" data-remove-qnum="${escapeAttr(entry.qnum)}">Remove</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function bindRemoveHandlers(container) {
  container.querySelectorAll("[data-remove-qnum]").forEach((button) => {
    button.addEventListener("click", async () => {
      const qnum = Number(button.getAttribute("data-remove-qnum") || 0);
      if (!qnum) return;

      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = "Removing...";

      try {
        await API.removeFromRevisit(qnum);
        showToast("Removed from revisit queue.", "success");
        await loadRevisitQueue();
      } catch (err) {
        showToast(`Failed to remove: ${err.message}`, "error");
        button.disabled = false;
        button.textContent = originalText || "Remove";
      }
    });
  });
}

function showToast(message, type) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    document.body.appendChild(toast);
  }

  toast.textContent = message;
  toast.className = `toast toast-${type || "info"} toast-show`;

  setTimeout(() => {
    toast.classList.remove("toast-show");
  }, 2600);
}

function normalizeDifficulty(value) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "easy" || text === "medium" || text === "hard") return text;
  return "unknown";
}

function titleCase(value) {
  return String(value || "")
    .toLowerCase()
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
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
    return String(dateStr);
  }
}

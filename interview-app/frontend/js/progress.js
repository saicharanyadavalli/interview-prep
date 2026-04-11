/**
 * progress.js - Immersive progress analytics page logic.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("progress", { requireLogin: true });
  loadProgress();
});

async function loadProgress() {
  const difficultyRings = document.getElementById("difficultyRings");
  const consistencyHeatmap = document.getElementById("consistencyHeatmap");
  const milestoneRow = document.getElementById("milestoneRow");
  const historyList = document.getElementById("historyList");
  const attemptedBadge = document.getElementById("attemptedBadge");
  const goalFill = document.getElementById("goalFill");
  const goalText = document.getElementById("goalText");

  if (!difficultyRings || !consistencyHeatmap || !milestoneRow || !historyList || !attemptedBadge || !goalFill || !goalText) {
    return;
  }

  difficultyRings.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading difficulty stats...</p>';
  consistencyHeatmap.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading activity...</p>';
  milestoneRow.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading milestones...</p>';
  historyList.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading history...</p>';

  try {
    const data = await API.getUserProgress();
    const stats = data && data.stats ? data.stats : {};
    const recent = Array.isArray(data && data.recent) ? data.recent : [];

    const difficultyStats = deriveDifficultyStats(stats, recent);

    attemptedBadge.textContent = `${Number(stats.total_attempted || 0)} Attempted`;
    renderDifficultyRings(difficultyRings, difficultyStats);
    renderConsistencyHeatmap(consistencyHeatmap, recent);
    renderMilestones(milestoneRow, stats, difficultyStats, recent);
    renderSolvedGoal(goalFill, goalText, Number(stats.solved_count || 0));
    renderHistory(historyList, recent);
  } catch (err) {
    renderDifficultyRings(difficultyRings, {
      easy: { attempted: 0, solved: 0, percent: 0 },
      medium: { attempted: 0, solved: 0, percent: 0 },
      hard: { attempted: 0, solved: 0, percent: 0 },
    });
    renderConsistencyHeatmap(consistencyHeatmap, []);
    renderMilestones(milestoneRow, {}, {}, []);
    renderSolvedGoal(goalFill, goalText, 0);
    historyList.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">📊</p>
        <p>No progress data yet.</p>
        <p class="text-sm text-muted">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function deriveDifficultyStats(stats, recent) {
  const attempted = {
    easy: Number(stats.easy_attempted || 0),
    medium: Number(stats.medium_attempted || 0),
    hard: Number(stats.hard_attempted || 0),
  };

  const solved = {
    easy: Number(stats.easy_solved || 0),
    medium: Number(stats.medium_solved || 0),
    hard: Number(stats.hard_solved || 0),
  };

  const hasBreakdown = Object.values(attempted).some((value) => value > 0) || Object.values(solved).some((value) => value > 0);

  if (!hasBreakdown) {
    (Array.isArray(recent) ? recent : []).forEach((entry) => {
      const difficulty = normalizeDifficulty(entry && entry.difficulty);
      if (!Object.prototype.hasOwnProperty.call(attempted, difficulty)) {
        return;
      }
      attempted[difficulty] += 1;
      if (Boolean(entry && entry.is_solved)) {
        solved[difficulty] += 1;
      }
    });
  }

  return {
    easy: finalizeDifficultyStats(attempted.easy, solved.easy),
    medium: finalizeDifficultyStats(attempted.medium, solved.medium),
    hard: finalizeDifficultyStats(attempted.hard, solved.hard),
  };
}

function finalizeDifficultyStats(attempted, solved) {
  const safeAttempted = Math.max(0, Number(attempted || 0));
  const safeSolved = Math.max(0, Number(solved || 0));
  const denominator = Math.max(safeAttempted, safeSolved);
  const percent = denominator > 0 ? Math.round((safeSolved / denominator) * 100) : 0;
  return {
    attempted: denominator,
    solved: safeSolved,
    percent,
  };
}

function renderDifficultyRings(container, stats) {
  const ringConfigs = [
    { key: "easy", label: "Easy", className: "easy" },
    { key: "medium", label: "Medium", className: "medium" },
    { key: "hard", label: "Hard", className: "hard" },
  ];

  const radius = 54;
  const circumference = 2 * Math.PI * radius;

  container.innerHTML = ringConfigs
    .map((config) => {
      const item = stats[config.key] || { attempted: 0, solved: 0, percent: 0 };
      const progress = Math.max(0, Math.min(100, Number(item.percent || 0))) / 100;
      const dashOffset = circumference * (1 - progress);

      return `
        <article class="progress-v3-ring-card ${config.className}">
          <div class="progress-v3-ring" role="img" aria-label="${config.label} solved ${item.solved} out of ${item.attempted}">
            <svg viewBox="0 0 140 140">
              <circle class="ring-bg" cx="70" cy="70" r="${radius}"></circle>
              <circle
                class="ring-fill"
                cx="70"
                cy="70"
                r="${radius}"
                stroke-dasharray="${circumference.toFixed(2)}"
                stroke-dashoffset="${dashOffset.toFixed(2)}"
              ></circle>
            </svg>
            <div class="progress-v3-ring-center">
              <p class="progress-v3-ring-value">${item.solved}</p>
              <p class="progress-v3-ring-unit">Solved</p>
            </div>
          </div>
          <p class="progress-v3-ring-title">${config.label}</p>
          <p class="progress-v3-ring-meta">${item.solved}/${item.attempted} completed • ${item.percent}%</p>
        </article>
      `;
    })
    .join("");
}

function renderConsistencyHeatmap(container, recent) {
  const countsByDate = buildActivityMap(recent);
  const totalDays = 56;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const cells = [];
  for (let offset = totalDays - 1; offset >= 0; offset -= 1) {
    const date = new Date(today);
    date.setDate(today.getDate() - offset);
    const key = toDateKey(date);
    const attempts = Number(countsByDate[key] || 0);
    const intensity = Math.min(4, attempts);

    cells.push(`
      <span
        class="progress-v3-heat-cell intensity-${intensity}"
        title="${formatDate(date.toISOString())}: ${attempts} practice session${attempts === 1 ? "" : "s"}"
      ></span>
    `);
  }

  container.innerHTML = cells.join("");
}

function buildActivityMap(recent) {
  const map = {};
  (Array.isArray(recent) ? recent : []).forEach((entry) => {
    if (!entry || !entry.updated_at) return;
    const parsed = new Date(entry.updated_at);
    if (Number.isNaN(parsed.getTime())) return;

    parsed.setHours(0, 0, 0, 0);
    const key = toDateKey(parsed);
    map[key] = Number(map[key] || 0) + 1;
  });
  return map;
}

function renderMilestones(container, stats, difficultyStats, recent) {
  const totalAttempted = Number(stats.total_attempted || 0);
  const solvedCount = Number(stats.solved_count || 0);
  const revisitCount = Number(stats.revisit_count || 0);
  const streak = calculateStreak(recent);

  const totalDifficultySolved =
    Number((difficultyStats.easy && difficultyStats.easy.solved) || 0)
    + Number((difficultyStats.medium && difficultyStats.medium.solved) || 0)
    + Number((difficultyStats.hard && difficultyStats.hard.solved) || 0);

  const milestones = [
    {
      label: "10 Attempts",
      sublabel: `${Math.min(totalAttempted, 10)} / 10`,
      unlocked: totalAttempted >= 10,
    },
    {
      label: "25 Solved",
      sublabel: `${Math.min(solvedCount, 25)} / 25`,
      unlocked: solvedCount >= 25,
    },
    {
      label: "3-Day Streak",
      sublabel: `${Math.min(streak, 3)} / 3`,
      unlocked: streak >= 3,
    },
    {
      label: "Queue Control",
      sublabel: revisitCount <= 5 ? "Under 5" : `${revisitCount} in queue`,
      unlocked: revisitCount <= 5,
    },
    {
      label: "Difficulty Master",
      sublabel: `${totalDifficultySolved} solved`,
      unlocked: totalDifficultySolved >= 15,
    },
  ];

  container.innerHTML = milestones
    .map((item) => `
      <article class="progress-v3-milestone ${item.unlocked ? "is-unlocked" : ""}">
        <p class="progress-v3-milestone-label">${item.label}</p>
        <p class="progress-v3-milestone-sub">${item.sublabel}</p>
      </article>
    `)
    .join("");
}

function calculateStreak(recent) {
  const uniqueDays = new Set(
    (Array.isArray(recent) ? recent : [])
      .map((entry) => {
        if (!entry || !entry.updated_at) return "";
        const date = new Date(entry.updated_at);
        if (Number.isNaN(date.getTime())) return "";
        date.setHours(0, 0, 0, 0);
        return toDateKey(date);
      })
      .filter(Boolean)
  );

  let streak = 0;
  const cursor = new Date();
  cursor.setHours(0, 0, 0, 0);

  while (true) {
    const key = toDateKey(cursor);
    if (!uniqueDays.has(key)) break;
    streak += 1;
    cursor.setDate(cursor.getDate() - 1);
  }

  return streak;
}

function renderSolvedGoal(goalFill, goalText, solvedCount) {
  const target = 100;
  const progress = Math.max(0, Math.min(100, Math.round((Number(solvedCount || 0) / target) * 100)));
  goalFill.style.width = `${progress}%`;
  goalText.textContent = `${Number(solvedCount || 0)} / ${target}`;
}

function renderHistory(container, recent) {
  if (!Array.isArray(recent) || !recent.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">📝</p>
        <p>No practice history yet. Start solving questions to populate this timeline.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = recent
    .map((entry) => {
      const difficulty = normalizeDifficulty(entry && entry.difficulty);
      const difficultyLabel = titleCase(difficulty || "unknown");

      const solved = Boolean(entry && entry.is_solved);
      const revisit = Boolean(entry && entry.revisit);

      let statusClass = "not-solved";
      let statusLabel = "Not Solved";
      if (revisit && solved) {
        statusClass = "revisit";
        statusLabel = "Solved + Revisit";
      } else if (revisit) {
        statusClass = "revisit";
        statusLabel = "Revisit";
      } else if (solved) {
        statusClass = "solved";
        statusLabel = "Solved";
      }

      return `
        <article class="progress-v3-history-card diff-${difficulty}">
          <div class="progress-v3-history-head">
            <h4>${escapeHtml(entry.question_title || entry.question_id || "Untitled Question")}</h4>
            <span class="pill progress-v3-diff-pill ${difficulty}">${escapeHtml(difficultyLabel)}</span>
          </div>
          <p class="progress-v3-history-meta">${escapeHtml(entry.company || "Unknown Company")} • ${formatDate(entry.updated_at)}</p>
          <p class="progress-v3-history-status ${statusClass}">${statusLabel}</p>
          <div class="progress-v3-history-actions">
            <a href="solve.html?qnum=${encodeURIComponent(entry.qnum || "")}" class="btn btn-sm btn-primary">Practice Again</a>
          </div>
        </article>
      `;
    })
    .join("");
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

function toDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDate(dateStr) {
  if (!dateStr) return "Date unavailable";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return String(dateStr);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

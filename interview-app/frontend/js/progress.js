/**
 * progress.js - Immersive progress analytics page logic.
 */

document.addEventListener("DOMContentLoaded", async () => {
  await initSidebar("progress", { requireLogin: true });
  loadProgress();
});

async function loadProgress() {
  const refs = {
    difficultyRings: document.getElementById("difficultyRings"),
    difficultyScopeTabs: document.getElementById("difficultyScopeTabs"),
    consistencyHeatmap: document.getElementById("consistencyHeatmap"),
    milestoneRow: document.getElementById("milestoneRow"),
    historyList: document.getElementById("historyList"),
    attemptedBadge: document.getElementById("attemptedBadge"),
    goalFill: document.getElementById("goalFill"),
    goalText: document.getElementById("goalText"),
    topicChips: document.getElementById("topicChips"),
    topicDetail: document.getElementById("topicDetail"),
    topicInsightSummary: document.getElementById("topicInsightSummary"),
    learningTrackProgressList: document.getElementById("learningTrackProgressList"),
  };

  if (Object.values(refs).some((value) => !value)) {
    return;
  }

  refs.difficultyRings.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading difficulty stats...</p>';
  refs.consistencyHeatmap.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading activity...</p>';
  refs.milestoneRow.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading milestones...</p>';
  refs.historyList.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading history...</p>';
  refs.topicChips.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading topics...</p>';
  refs.topicDetail.innerHTML = "";

  try {
    const data = await API.getUserProgress();
    const stats = data && data.stats ? data.stats : {};
    const recent = Array.isArray(data && data.recent) ? data.recent : [];
    const rawTopicBreakdown = Array.isArray(data && data.topic_breakdown) ? data.topic_breakdown : [];

    const allTopicData = buildAllTopicData(stats);
    const topicBreakdown = mergeTopicBreakdownWithFilterTopics(rawTopicBreakdown, getFilterBuilderTopics());

    const state = {
      activeTopicKey: "all",
      activeScope: "all",
      allTopicData,
      topicBreakdown,
    };

    function getActiveTopicData() {
      if (state.activeTopicKey === "all") {
        return state.allTopicData;
      }
      return state.topicBreakdown.find((item) => normalizeTopicKey(item.topic_key) === state.activeTopicKey) || state.allTopicData;
    }

    function renderDifficultyArea() {
      const activeTopic = getActiveTopicData();
      const difficultyStats = deriveDifficultyStatsFromTopic(activeTopic);

      renderDifficultyScopeTabs(refs.difficultyScopeTabs, state.activeScope, (scope) => {
        state.activeScope = scope;
        renderDifficultyArea();
      });

      renderDifficultyRings(refs.difficultyRings, difficultyStats, state.activeScope);
      updateSolvedBadge(refs.attemptedBadge, activeTopic, state.activeScope);
    }

    function renderTopicArea() {
      renderTopicInsights(
        refs.topicChips,
        refs.topicDetail,
        refs.topicInsightSummary,
        state.topicBreakdown,
        state.allTopicData,
        state.activeTopicKey,
        (topicKey) => {
          state.activeTopicKey = topicKey;
          renderTopicArea();
          renderDifficultyArea();
        }
      );
    }

    renderDifficultyArea();
    renderConsistencyHeatmap(refs.consistencyHeatmap, recent);
    renderMilestones(refs.milestoneRow, stats, deriveDifficultyStatsFromTopic(state.allTopicData), recent);
    renderSolvedGoal(
      refs.goalFill,
      refs.goalText,
      Number(state.allTopicData.solved_questions || 0),
      Number(state.allTopicData.total_questions || 0)
    );
    renderTopicArea();
    renderHistory(refs.historyList, recent);
  } catch (err) {
    renderDifficultyScopeTabs(refs.difficultyScopeTabs, "all", function () {});
    renderDifficultyRings(refs.difficultyRings, {
      easy: { attempted: 0, solved: 0, percent: 0 },
      medium: { attempted: 0, solved: 0, percent: 0 },
      hard: { attempted: 0, solved: 0, percent: 0 },
    }, "all");
    updateSolvedBadge(refs.attemptedBadge, buildAllTopicData({}), "all");
    renderConsistencyHeatmap(refs.consistencyHeatmap, []);
    renderMilestones(refs.milestoneRow, {}, {}, []);
    renderSolvedGoal(refs.goalFill, refs.goalText, 0, 0);
    renderTopicInsights(refs.topicChips, refs.topicDetail, refs.topicInsightSummary, [], buildAllTopicData({}), "all", function () {});
    refs.historyList.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">📊</p>
        <p>No progress data yet.</p>
        <p class="text-sm text-muted">${escapeHtml(err.message)}</p>
      </div>
    `;
  }

  await renderLearningTrackCourseTracking(refs);
}

async function renderLearningTrackCourseTracking(refs) {
  if (!refs.learningTrackProgressList) {
    return;
  }

  let tracks = Array.isArray(window.LEARNING_TRACKS) ? window.LEARNING_TRACKS : [];
  try {
    const remote = await API.getLearningTracks();
    if (remote && Array.isArray(remote.tracks) && remote.tracks.length) {
      tracks = remote.tracks;
    }
  } catch (_) {
    // Keep local fallback.
  }

  if (!tracks.length) {
    refs.learningTrackProgressList.innerHTML = '<p class="text-sm text-muted">No learning tracks available yet.</p>';
    return;
  }

  const progressRows = await Promise.all(
    tracks.map(async (track) => {
      const trackId = String((track && track.track_id) || "").trim();
      if (!trackId) return null;

      const localMeta = typeof getLearningTrackById === "function" ? getLearningTrackById(trackId) : null;
      const icon = String((localMeta && localMeta.icon) || track.icon || "📘");
      const name = String((track && track.display_name) || (localMeta && localMeta.display_name) || "Learning Track");
      const href = String((localMeta && localMeta.course_href) || track.course_href || "#");

      try {
        const data = await API.getLearningTrackProgress(trackId);
        return { icon, name, href, data, totalHint: Number(track.step_count || 0) };
      } catch (_) {
        return { icon, name, href, data: null, totalHint: Number(track.step_count || 0) };
      }
    })
  );

  refs.learningTrackProgressList.innerHTML = progressRows
    .filter(Boolean)
    .map((row) => {
      const total = Number((row.data && row.data.total_steps) || row.totalHint || 0);
      const completed = Number((row.data && row.data.completed_steps) || 0);
      const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
      return `
        <article class="progress-v3-track-item">
          <div class="progress-v3-card-head">
            <h4>${escapeHtml(`${row.icon} ${row.name}`)}</h4>
            <a href="${escapeHtml(row.href)}" class="btn btn-sm">Open Course</a>
          </div>
          <div class="progress-wrap">
            <div class="progress-fill" style="width:${Math.max(0, Math.min(100, percent))}%"></div>
          </div>
          <div class="progress-v3-system-design-meta">
            <span>${completed} / ${total} completed</span>
            <span>${percent}%</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function getFilterBuilderTopics() {
  const raw = Array.isArray(window.FILTER_BUILDER_DEFAULT_TOPICS) ? window.FILTER_BUILDER_DEFAULT_TOPICS : [];
  const seen = new Set();
  const topics = [];

  raw.forEach((topic) => {
    const label = String(topic || "").trim();
    const key = normalizeTopicKey(label);
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    topics.push({ topic_key: key, topic: label });
  });

  return topics;
}

function normalizeTopicKey(value) {
  return String(value || "").trim().toLowerCase();
}

function mergeTopicBreakdownWithFilterTopics(topicBreakdown, filterTopics) {
  const backendMap = new Map();

  (Array.isArray(topicBreakdown) ? topicBreakdown : []).forEach((entry) => {
    const key = normalizeTopicKey(entry && entry.topic_key ? entry.topic_key : entry && entry.topic);
    if (!key) return;

    backendMap.set(key, {
      topic_key: key,
      topic: String((entry && entry.topic) || key),
      total_questions: Number((entry && entry.total_questions) || 0),
      solved_questions: Number((entry && entry.solved_questions) || 0),
      easy_total_questions: Number((entry && entry.easy_total_questions) || 0),
      medium_total_questions: Number((entry && entry.medium_total_questions) || 0),
      hard_total_questions: Number((entry && entry.hard_total_questions) || 0),
      easy_solved_questions: Number((entry && entry.easy_solved_questions) || 0),
      medium_solved_questions: Number((entry && entry.medium_solved_questions) || 0),
      hard_solved_questions: Number((entry && entry.hard_solved_questions) || 0),
    });
  });

  const filterList = Array.isArray(filterTopics) ? filterTopics : [];
  if (!filterList.length) {
    return Array.from(backendMap.values()).sort((a, b) => {
      const totalDelta = Number(b.total_questions || 0) - Number(a.total_questions || 0);
      if (totalDelta !== 0) return totalDelta;
      return String(a.topic || "").localeCompare(String(b.topic || ""));
    });
  }

  const merged = filterList
    .map((entry) => {
      const label = String(entry && entry.topic ? entry.topic : "").trim();
      const key = normalizeTopicKey(entry && entry.topic_key ? entry.topic_key : label);
      if (!key) return null;

      const backend = backendMap.get(key);
      if (backend) {
        return {
          ...backend,
          topic: label || backend.topic,
        };
      }

      return {
        topic_key: key,
        topic: label || key,
        total_questions: 0,
        solved_questions: 0,
        easy_total_questions: 0,
        medium_total_questions: 0,
        hard_total_questions: 0,
        easy_solved_questions: 0,
        medium_solved_questions: 0,
        hard_solved_questions: 0,
      };
    })
    .filter(Boolean)
    .filter((item) => Number(item.total_questions || 0) > 0 || Number(item.solved_questions || 0) > 0);

  return merged;
}

function buildAllTopicData(stats) {
  return {
    topic_key: "all",
    topic: "All topics",
    total_questions: Number(stats.total_questions || 0),
    solved_questions: Number(stats.solved_total_questions || 0),
    easy_total_questions: Number(stats.easy_total_questions || 0),
    medium_total_questions: Number(stats.medium_total_questions || 0),
    hard_total_questions: Number(stats.hard_total_questions || 0),
    easy_solved_questions: Number(stats.easy_solved_total_questions || 0),
    medium_solved_questions: Number(stats.medium_solved_total_questions || 0),
    hard_solved_questions: Number(stats.hard_solved_total_questions || 0),
  };
}

function deriveDifficultyStatsFromTopic(topicData) {
  return {
    easy: finalizeDifficultyStats(topicData && topicData.easy_total_questions, topicData && topicData.easy_solved_questions),
    medium: finalizeDifficultyStats(topicData && topicData.medium_total_questions, topicData && topicData.medium_solved_questions),
    hard: finalizeDifficultyStats(topicData && topicData.hard_total_questions, topicData && topicData.hard_solved_questions),
  };
}

function finalizeDifficultyStats(totalValue, solvedValue) {
  const total = Math.max(0, Number(totalValue || 0));
  const solved = Math.max(0, Number(solvedValue || 0));
  const percent = total > 0 ? Math.round((solved / total) * 100) : 0;

  return {
    attempted: total,
    solved,
    percent,
  };
}

function renderDifficultyScopeTabs(container, activeScope, onChange) {
  if (!container) return;

  const scopes = [
    { key: "all", label: "All" },
    { key: "easy", label: "Easy" },
    { key: "medium", label: "Medium" },
    { key: "hard", label: "Hard" },
  ];

  container.innerHTML = scopes
    .map((scope) => `
      <button type="button" class="progress-v3-scope-tab ${activeScope === scope.key ? "is-active" : ""}" data-scope="${scope.key}">
        ${scope.label}
      </button>
    `)
    .join("");

  container.querySelectorAll(".progress-v3-scope-tab").forEach((button) => {
    button.addEventListener("click", () => {
      const scope = String(button.getAttribute("data-scope") || "all");
      onChange(scope);
    });
  });
}

function updateSolvedBadge(badgeEl, topicData, scope) {
  if (!badgeEl) return;

  const data = topicData || buildAllTopicData({});

  let solved = Number(data.solved_questions || 0);
  let total = Number(data.total_questions || 0);
  let suffix = "Solved";

  if (scope === "easy") {
    solved = Number(data.easy_solved_questions || 0);
    total = Number(data.easy_total_questions || 0);
    suffix = "Easy Solved";
  } else if (scope === "medium") {
    solved = Number(data.medium_solved_questions || 0);
    total = Number(data.medium_total_questions || 0);
    suffix = "Medium Solved";
  } else if (scope === "hard") {
    solved = Number(data.hard_solved_questions || 0);
    total = Number(data.hard_total_questions || 0);
    suffix = "Hard Solved";
  }

  badgeEl.textContent = `${solved} / ${total} ${suffix}`;
}

function renderDifficultyRings(container, stats, activeScope) {
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
      const isMuted = activeScope !== "all" && activeScope !== config.key;

      return `
        <article class="progress-v3-ring-card ${config.className} ${isMuted ? "is-muted" : ""}">
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

function renderSolvedGoal(goalFill, goalText, solvedCount, totalQuestions) {
  const solved = Math.max(0, Number(solvedCount || 0));
  const total = Math.max(0, Number(totalQuestions || 0));
  const progress = total > 0 ? Math.round((solved / total) * 100) : 0;

  goalFill.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  goalText.textContent = `${solved} / ${total}`;
}

function renderTopicInsights(chipsEl, detailEl, summaryEl, topicBreakdown, allTopicData, activeTopicKey, onTopicSelect) {
  if (!chipsEl || !detailEl || !summaryEl) return;

  const topics = Array.isArray(topicBreakdown) ? topicBreakdown : [];
  const normalizedActiveKey = normalizeTopicKey(activeTopicKey || "all") || "all";

  const activeTopic = normalizedActiveKey === "all"
    ? allTopicData
    : (topics.find((item) => normalizeTopicKey(item.topic_key) === normalizedActiveKey) || allTopicData);

  const allChip = `
    <button type="button" class="progress-v3-topic-chip ${normalizedActiveKey === "all" ? "is-active" : ""}" data-topic-key="all">
      All Topics
      <span>${Number(allTopicData.solved_questions || 0)}/${Number(allTopicData.total_questions || 0)}</span>
    </button>
  `;

  const topicChips = topics
    .map((topic) => {
      const key = normalizeTopicKey(topic.topic_key);
      const solved = Number(topic.solved_questions || 0);
      const total = Number(topic.total_questions || 0);
      return `
        <button type="button" class="progress-v3-topic-chip ${normalizedActiveKey === key ? "is-active" : ""}" data-topic-key="${escapeAttr(key)}">
          ${escapeHtml(topic.topic || "Untitled")}
          <span>${solved}/${total}</span>
        </button>
      `;
    })
    .join("");

  chipsEl.innerHTML = allChip + topicChips;

  chipsEl.querySelectorAll(".progress-v3-topic-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const key = normalizeTopicKey(button.getAttribute("data-topic-key") || "all") || "all";
      onTopicSelect(key);
    });
  });

  summaryEl.textContent = `${activeTopic.topic} • ${Number(activeTopic.solved_questions || 0)}/${Number(activeTopic.total_questions || 0)} solved`;
  detailEl.innerHTML = renderTopicDetailCard(activeTopic);
}

function renderTopicDetailCard(topicData) {
  const easyRow = buildTopicDifficultyRow("Easy", topicData.easy_solved_questions, topicData.easy_total_questions, "easy");
  const mediumRow = buildTopicDifficultyRow("Medium", topicData.medium_solved_questions, topicData.medium_total_questions, "medium");
  const hardRow = buildTopicDifficultyRow("Hard", topicData.hard_solved_questions, topicData.hard_total_questions, "hard");

  return `
    <div class="progress-v3-topic-detail-card">
      <div class="progress-v3-topic-overview">
        <p class="progress-v3-topic-title">${escapeHtml(topicData.topic || "All topics")}</p>
        <p class="progress-v3-topic-overall">${Number(topicData.solved_questions || 0)} / ${Number(topicData.total_questions || 0)} solved</p>
      </div>
      <div class="progress-v3-topic-rows">
        ${easyRow}
        ${mediumRow}
        ${hardRow}
      </div>
    </div>
  `;
}

function buildTopicDifficultyRow(label, solvedValue, totalValue, className) {
  const solved = Number(solvedValue || 0);
  const total = Number(totalValue || 0);
  const percent = total > 0 ? Math.round((solved / total) * 100) : 0;

  return `
    <div class="progress-v3-topic-row ${className}">
      <div class="progress-v3-topic-row-head">
        <span>${label}</span>
        <span>${solved}/${total} • ${percent}%</span>
      </div>
      <div class="progress-v3-topic-row-bar"><span style="width:${percent}%"></span></div>
    </div>
  `;
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

function escapeAttr(text) {
  return String(text || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

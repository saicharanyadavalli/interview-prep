/**
 * system-design.js - System Design Course page logic.
 */

const SYSTEM_DESIGN_TITLES = [
  "Join the Community",
  "Scale From Zero To Millions Of Users",
  "Back-of-the-envelope Estimation",
  "A Framework For System Design Interviews",
  "Design A Rate Limiter",
  "Design Consistent Hashing",
  "Design A Key-value Store",
  "Design A Unique ID Generator In Distributed Systems",
  "Design A URL Shortener",
  "Design A Web Crawler",
  "Design A Notification System",
  "Design A News Feed System",
  "Design A Chat System",
  "Design A Search Autocomplete System",
  "Design YouTube",
  "Design Google Drive",
  "Proximity Service",
  "Nearby Friends",
  "Google Maps",
  "Distributed Message Queue",
  "Metrics Monitoring and Alerting System",
  "Ad Click Event Aggregation",
  "Hotel Reservation System",
  "Distributed Email Service",
  "S3-like Object Storage",
  "Real-time Gaming Leaderboard",
  "Payment System",
  "Digital Wallet",
  "Stock Exchange",
  "The Learning Continues",
];

const SYSTEM_DESIGN_CHAPTERS = SYSTEM_DESIGN_TITLES.map((title, index) => {
  const stepNo = index + 1;
  const stepToken = String(stepNo).padStart(2, "0");
  return {
    step_no: stepNo,
    title,
    local_html: `system-design/lessons/step-${stepToken}.html`,
  };
});

document.addEventListener("DOMContentLoaded", async () => {
  const user = await initSidebar("system-design", { requireLogin: true });
  if (!user) return;

  const { session } = await getSession();
  if (session) {
    await syncSessionWithBackend(session.access_token);
  }

  await loadSystemDesignCoursePage();
});

async function loadSystemDesignCoursePage() {
  const refs = {
    stepsList: document.getElementById("systemDesignSteps"),
    fileCountBadge: document.getElementById("sdCompletionBadge"),
    filesPill: document.getElementById("sdCompletedPill"),
  };

  if (!refs.stepsList) {
    return;
  }

  const chapters = SYSTEM_DESIGN_CHAPTERS.map((chapter) => ({
    step_no: Number(chapter.step_no),
    title: String(chapter.title || "").trim(),
    local_html: normalizeLocalPath(String(chapter.local_html || "").trim()),
  })).filter((chapter) => Number.isFinite(chapter.step_no) && chapter.step_no > 0 && chapter.local_html);

  updateFileCount(refs, chapters.length);
  renderStepsList(refs, chapters);
}

function renderStepsList(refs, steps) {
  if (!Array.isArray(steps) || !steps.length) {
    refs.stepsList.innerHTML = '<p class="text-muted text-sm">No chapter links available.</p>';
    return;
  }

  refs.stepsList.innerHTML = steps
    .map((step) => {
      const stepNo = Number(step.step_no || 0);
      const filePath = normalizeLocalPath(step.local_html || "");
      const encodedPath = encodeURI(filePath);
      return `
        <div class="system-design-row" data-step-no="${stepNo}">
          <div class="system-design-row-main">
            <p class="system-design-step-index">Step ${stepNo}</p>
            <p class="system-design-step-title">${escapeHtml(step.title || `Step ${stepNo}`)}</p>
          </div>
          <a class="btn btn-sm btn-primary system-design-open-btn" href="${encodedPath}">Open</a>
        </div>
      `;
    })
    .join("");
}

function updateFileCount(refs, overrideCount = null) {
  const total = Number.isFinite(Number(overrideCount)) ? Number(overrideCount) : SYSTEM_DESIGN_CHAPTERS.length;
  if (refs.fileCountBadge) {
    refs.fileCountBadge.textContent = `${total} files`;
  }
  if (refs.filesPill) {
    refs.filesPill.textContent = `${total} files`;
  }
}

function normalizeLocalPath(path) {
  return String(path || "").replace(/^[./]+/, "").trim();
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}

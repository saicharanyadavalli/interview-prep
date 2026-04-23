/**
 * system-design.js - Learning-track course page logic.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const trackId = resolveTrackIdFromPage();
  const track = typeof getLearningTrackById === "function" ? getLearningTrackById(trackId) : null;
  if (!track) {
    return;
  }

  const user = await initSidebar(trackId, { requireLogin: true });
  if (!user) return;

  const { session } = await getSession();
  if (session) {
    await syncSessionWithBackend(session.access_token);
  }

  await loadLearningTrackCoursePage(track);
});

async function loadLearningTrackCoursePage(track) {
  const refs = {
    stepsList: document.getElementById("systemDesignSteps"),
    fileCountBadge: document.getElementById("sdCompletionBadge"),
    filesPill: document.getElementById("sdCompletedPill"),
    pageTitle: document.getElementById("learningTrackTitle"),
    pageEmoji: document.getElementById("learningTrackEmoji"),
    chaptersLabel: document.getElementById("learningTrackChaptersLabel"),
  };

  if (!refs.stepsList) {
    return;
  }

  if (refs.pageTitle) {
    refs.pageTitle.textContent = `${track.display_name} Course`;
  }
  if (refs.pageEmoji) {
    refs.pageEmoji.textContent = track.icon || "📘";
  }
  if (refs.chaptersLabel) {
    refs.chaptersLabel.textContent = `${track.display_name} Chapters`;
  }

  const chapters = await loadTrackChapters(track);

  updateFileCount(refs, chapters.length);
  renderStepsList(refs, chapters);
}

async function loadTrackChapters(track) {
  const indexPath = `assets/${track.assets_slug}/course-index.json`;
  try {
    const response = await fetch(indexPath, { cache: "no-store" });
    if (response.ok) {
      const payload = await response.json();
      const steps = Array.isArray(payload && payload.steps) ? payload.steps : [];
      const normalized = steps
        .map((chapter) => ({
          step_no: Number(chapter && chapter.step_no),
          title: String((chapter && chapter.title) || "").trim(),
          local_html: normalizeLocalPath(String((chapter && chapter.local_html) || "").trim()),
        }))
        .filter((chapter) => Number.isFinite(chapter.step_no) && chapter.step_no > 0);

      if (normalized.length) {
        return normalized.map((chapter) => ({
          ...chapter,
          local_html: chapter.local_html || `${track.lessons_root}/step-${String(chapter.step_no).padStart(2, "0")}.html`,
        }));
      }
    }
  } catch (_) {
    // Fall back to generated default chapter links.
  }

  const totalSteps = Number(track.step_count || 0);
  return Array.from({ length: totalSteps }, (_, index) => {
    const stepNo = index + 1;
    return {
      step_no: stepNo,
      title: `Step ${stepNo}`,
      local_html: `${track.lessons_root}/step-${String(stepNo).padStart(2, "0")}.html`,
    };
  });
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
  const total = Number.isFinite(Number(overrideCount)) ? Number(overrideCount) : 0;
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

function resolveTrackIdFromPage() {
  const bodyTrackId = String((document.body && document.body.dataset && document.body.dataset.trackId) || "").trim();
  if (bodyTrackId) {
    return bodyTrackId;
  }
  return "system-design";
}

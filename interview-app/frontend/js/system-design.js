/**
 * system-design.js - Learning-track course page logic.
 *
 * Shared across all 5 learning track HTML pages.
 * Each page sets data-track-id on <body> to identify itself.
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

  updateChapterCount(refs, chapters.length);
  renderChaptersList(refs, chapters, track);
}

/**
 * Load titles from the local course-index.json file.
 * Returns a Map of step_no → { title, local_html }.
 */
async function loadLocalCourseIndex(track) {
  const indexPath = `assets/${track.assets_slug}/course-index.json`;
  try {
    const response = await fetch(indexPath, { cache: "no-store" });
    if (!response.ok) return null;
    const payload = await response.json();
    const steps = Array.isArray(payload && payload.steps) ? payload.steps : [];
    const map = {};
    steps.forEach((chapter) => {
      const stepNo = Number(chapter && chapter.step_no);
      if (!Number.isFinite(stepNo) || stepNo <= 0) return;
      map[stepNo] = {
        title: String((chapter && chapter.title) || "").trim(),
        local_html: normalizeLocalPath(String((chapter && chapter.local_html) || "").trim()),
      };
    });
    return Object.keys(map).length > 0 ? map : null;
  } catch (_) {
    return null;
  }
}

async function loadTrackChapters(track) {
  // 1. Always try to load the local course-index.json for titles
  const localIndex = await loadLocalCourseIndex(track);

  // 2. Try API for progress data (which also contains titles from backend)
  let apiSteps = null;
  try {
    const progressResponse = await API.getLearningTrackProgress(track.track_id);
    if (progressResponse && progressResponse.steps && progressResponse.steps.length > 0) {
      apiSteps = progressResponse.steps;
    }
  } catch (error) {
    console.warn("API progress fetch failed, using local data", error);
  }

  // 3. Build the final chapter list
  const totalSteps = Number(track.step_count || 0);

  if (apiSteps) {
    // API returned data — merge with local titles (local JSON has better titles)
    return apiSteps.map(step => {
      const localData = localIndex ? localIndex[step.step_no] : null;
      const title = (localData && localData.title) || step.title || `Chapter ${step.step_no}`;
      return {
        step_no: step.step_no,
        title: title,
        completed: step.completed,
        local_html: (localData && localData.local_html)
          || `${track.lessons_root}/step-${String(step.step_no).padStart(2, "0")}.html`,
      };
    });
  }

  if (localIndex) {
    // No API but we have local JSON — use titles from there
    return Array.from({ length: totalSteps }, (_, index) => {
      const stepNo = index + 1;
      const localData = localIndex[stepNo];
      return {
        step_no: stepNo,
        title: (localData && localData.title) || `Chapter ${stepNo}`,
        completed: false,
        local_html: (localData && localData.local_html)
          || `${track.lessons_root}/step-${String(stepNo).padStart(2, "0")}.html`,
      };
    });
  }

  // Final fallback — no API, no local JSON
  return Array.from({ length: totalSteps }, (_, index) => {
    const stepNo = index + 1;
    return {
      step_no: stepNo,
      title: `Chapter ${stepNo}`,
      completed: false,
      local_html: `${track.lessons_root}/step-${String(stepNo).padStart(2, "0")}.html`,
    };
  });
}

function renderChaptersList(refs, chapters, track) {
  if (!Array.isArray(chapters) || !chapters.length) {
    refs.stepsList.innerHTML = '<p class="text-muted text-sm">No chapters available.</p>';
    return;
  }

  refs.stepsList.innerHTML = chapters
    .map((chapter) => {
      const chapterNo = Number(chapter.step_no || 0);
      const filePath = normalizeLocalPath(chapter.local_html || "");
      const encodedPath = encodeURI(filePath);
      const isCompleted = chapter.completed ? "checked" : "";
      return `
        <div class="system-design-row" data-step-no="${chapterNo}">
          <div class="system-design-row-main" style="display: flex; align-items: center; gap: 0.8rem;">
            <label class="custom-checkbox" style="margin-bottom: 0;">
              <input type="checkbox" class="sd-step-checkbox" data-step="${chapterNo}" ${isCompleted} />
              <span class="checkmark"></span>
            </label>
            <div>
              <p class="system-design-step-index" style="margin: 0; font-size: 0.85rem; color: var(--text-muted);">Chapter ${chapterNo}</p>
              <p class="system-design-step-title" style="margin: 0; font-weight: 500;">${escapeHtml(chapter.title || `Chapter ${chapterNo}`)}</p>
            </div>
          </div>
          <a class="btn btn-sm btn-primary system-design-open-btn" href="${encodedPath}">Open</a>
        </div>
      `;
    })
    .join("");

  // Add event listeners to checkboxes
  refs.stepsList.querySelectorAll('.sd-step-checkbox').forEach(box => {
    box.addEventListener('change', async (e) => {
      const stepNo = e.target.dataset.step;
      const completed = e.target.checked;
      const trackId = resolveTrackIdFromPage();
      try {
        await API.updateLearningTrackProgress(trackId, stepNo, completed);
      } catch (err) {
        console.error("Failed to update progress", err);
        // Revert check on failure
        e.target.checked = !completed;
      }
    });
  });
}

function updateChapterCount(refs, overrideCount = null) {
  const total = Number.isFinite(Number(overrideCount)) ? Number(overrideCount) : 0;
  if (refs.fileCountBadge) {
    refs.fileCountBadge.textContent = `${total} chapters`;
  }
  if (refs.filesPill) {
    refs.filesPill.textContent = `${total} chapters`;
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

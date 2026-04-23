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
  try {
    const progressResponse = await API.getLearningTrackProgress(track.track_id);
    if (progressResponse && progressResponse.steps && progressResponse.steps.length > 0) {
      return progressResponse.steps.map(step => ({
        step_no: step.step_no,
        title: step.title,
        completed: step.completed,
        local_html: `${track.lessons_root}/step-${String(step.step_no).padStart(2, "0")}.html`,
      }));
    }
  } catch (error) {
    console.warn("API progress fetch failed, falling back to local json", error);
  }

  // Fallback to local json (may fail due to CORS on file://)
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
          completed: false,
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
      completed: false,
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
      const isCompleted = step.completed ? "checked" : "";
      return `
        <div class="system-design-row" data-step-no="${stepNo}">
          <div class="system-design-row-main" style="display: flex; align-items: center; gap: 0.8rem;">
            <label class="custom-checkbox" style="margin-bottom: 0;">
              <input type="checkbox" class="sd-step-checkbox" data-step="${stepNo}" ${isCompleted} />
              <span class="checkmark"></span>
            </label>
            <div>
              <p class="system-design-step-index" style="margin: 0; font-size: 0.85rem; color: var(--text-muted);">Step ${stepNo}</p>
              <p class="system-design-step-title" style="margin: 0; font-weight: 500;">${escapeHtml(step.title || `Step ${stepNo}`)}</p>
            </div>
          </div>
          <a class="btn btn-sm btn-primary system-design-open-btn" href="${encodedPath}">Open</a>
        </div>
      `;
    })
    .join("");

  // Add event listeners to newly inserted checkboxes
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

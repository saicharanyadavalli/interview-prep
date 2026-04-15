/**
 * system-design.js - System Design Course page logic.
 */

const systemDesignState = {
  steps: [],
  activeStepNo: null,
};

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
    chapterTitle: document.getElementById("sdChapterTitle"),
    chapterMeta: document.getElementById("sdChapterMeta"),
    chapterContent: document.getElementById("sdChapterContent"),
    sourceLink: document.getElementById("sdSourceLink"),
    fileCountBadge: document.getElementById("sdCompletionBadge"),
    filesPill: document.getElementById("sdCompletedPill"),
  };

  if (!refs.stepsList || !refs.chapterTitle || !refs.chapterMeta || !refs.chapterContent) {
    return;
  }

  try {
    const indexRes = await fetch("assets/system-design/course-index.json", { cache: "no-store" });

    if (!indexRes.ok) {
      throw new Error(`Failed to load course index (${indexRes.status})`);
    }

    const indexData = await indexRes.json();
    const steps = Array.isArray(indexData && indexData.steps) ? indexData.steps : [];
    systemDesignState.steps = steps
      .map((step) => ({
        step_no: Number(step && step.step_no),
        title: String((step && step.title) || "").trim(),
        source_url: String((step && step.source_url) || "").trim(),
        local_html: normalizeLocalPath(String((step && step.local_html) || "").trim()),
      }))
      .filter((step) => Number.isFinite(step.step_no) && step.step_no > 0 && step.local_html)
      .sort((a, b) => a.step_no - b.step_no);

    updateFileCount(refs);

    renderStepsList(refs);

    const initialStep = systemDesignState.steps[0] || null;
    if (initialStep) {
      setActiveStep(initialStep, refs);
      renderStepsList(refs);
    } else {
      refs.chapterTitle.textContent = "No chapter files found";
      refs.chapterMeta.textContent = "Could not find valid local HTML files in the course index.";
      refs.chapterContent.innerHTML = '<p class="text-muted">No chapter file paths are available.</p>';
    }
  } catch (error) {
    updateFileCount(refs, 0);
    refs.stepsList.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">!</p>
        <p>Unable to load System Design course.</p>
        <p class="text-sm text-muted">${escapeHtml(error.message || "Unknown error")}</p>
      </div>
    `;
  }
}

function renderStepsList(refs) {
  const steps = systemDesignState.steps;

  if (!steps.length) {
    refs.stepsList.innerHTML = '<p class="text-muted text-sm">No chapter data available.</p>';
    return;
  }

  refs.stepsList.innerHTML = steps
    .map((step) => {
      const stepNo = Number(step.step_no || 0);
      const active = stepNo === Number(systemDesignState.activeStepNo || 0);
      return `
        <button type="button" class="system-design-step-btn ${active ? "is-active" : ""}" data-step-no="${stepNo}">
          <span class="system-design-step-index">Step ${stepNo}</span>
          <span class="system-design-step-title">${escapeHtml(step.title || `Step ${stepNo}`)}</span>
          <span class="system-design-file-path">${escapeHtml(step.local_html || "")}</span>
          <span class="system-design-step-status open">Open HTML in new tab</span>
        </button>
      `;
    })
    .join("");

  refs.stepsList.querySelectorAll(".system-design-step-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const stepNo = Number(button.getAttribute("data-step-no") || 0);
      const step = systemDesignState.steps.find((item) => Number(item.step_no || 0) === stepNo);
      if (!step) return;

      setActiveStep(step, refs);
      renderStepsList(refs);
      openStepInNewTab(step, refs);
    });
  });
}

function setActiveStep(step, refs) {
  const stepNo = Number(step.step_no || 0);
  if (!stepNo) return;

  systemDesignState.activeStepNo = stepNo;

  const title = String(step.title || `Step ${stepNo}`).trim();
  const htmlPath = String(step.local_html || "").trim();
  const sourceUrl = String(step.source_url || "").trim();

  refs.chapterTitle.textContent = `Step ${stepNo}: ${title}`;
  refs.chapterMeta.textContent = htmlPath
    ? "Clicking the chapter opens this local HTML file in a new tab."
    : "Chapter file path unavailable.";

  if (refs.sourceLink) {
    refs.sourceLink.href = sourceUrl || "#";
    refs.sourceLink.style.pointerEvents = sourceUrl ? "auto" : "none";
    refs.sourceLink.style.opacity = sourceUrl ? "1" : "0.5";
  }

  refs.chapterContent.innerHTML = `
    <div class="empty-state">
      <p><strong>Local file:</strong></p>
      <p class="system-design-file-path">${escapeHtml(htmlPath || "(missing path)")}</p>
      <p class="text-sm text-muted">Select this chapter to open it in a new tab.</p>
    </div>
  `;
}

function openStepInNewTab(step, refs) {
  const htmlPath = String(step.local_html || "").trim();
  if (!htmlPath) {
    refs.chapterMeta.textContent = "Cannot open chapter because local file path is missing.";
    return;
  }

  const openedTab = window.open(encodeURI(htmlPath), "_blank", "noopener,noreferrer");
  if (openedTab) {
    refs.chapterMeta.textContent = `Opened ${htmlPath} in a new tab.`;
    return;
  }

  refs.chapterMeta.textContent = "Popup was blocked by the browser. Allow popups and try again.";
}

function updateFileCount(refs, overrideCount = null) {
  const total = Number.isFinite(Number(overrideCount)) ? Number(overrideCount) : systemDesignState.steps.length;
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

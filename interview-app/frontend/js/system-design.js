/**
 * system-design.js - System Design Course page logic.
 */

const SYSTEM_DESIGN_LOCAL_TICKS_KEY = "ipp_system_design_local_ticks_v1";

const systemDesignState = {
  steps: [],
  progressByStep: new Map(),
  saveInFlightByStep: new Set(),
};

document.addEventListener("DOMContentLoaded", async () => {
  const user = await initSidebar("system-design", { requireLogin: true });
  if (!user) return;

  const { session } = await getSession();
  if (session) {
    syncSessionWithBackend(session.access_token);
  }

  await loadSystemDesignCoursePage();
});

async function loadSystemDesignCoursePage() {
  const refs = {
    stepsList: document.getElementById("systemDesignSteps"),
    completionBadge: document.getElementById("sdCompletionBadge"),
    completedPill: document.getElementById("sdCompletedPill"),
    progressFill: document.getElementById("sdProgressFill"),
    progressText: document.getElementById("sdProgressText"),
  };

  if (Object.values(refs).some((el) => !el)) {
    return;
  }

  try {
    const indexRes = await fetch("assets/system-design/course-index.json", { cache: "no-store" });

    if (!indexRes.ok) {
      throw new Error(`Failed to load course index (${indexRes.status})`);
    }

    const indexData = await indexRes.json();
    const steps = Array.isArray(indexData && indexData.steps) ? indexData.steps : [];
    systemDesignState.steps = steps;
    systemDesignState.progressByStep = readLocalTickMap(steps);

    renderStepsList(refs);
  } catch (error) {
    refs.stepsList.innerHTML = `
      <div class="empty-state">
        <p class="empty-icon">??</p>
        <p>Unable to load System Design course.</p>
        <p class="text-sm text-muted">${escapeHtml(error.message || "Unknown error")}</p>
      </div>
    `;
  }
}

function renderStepsList(refs) {
  const steps = systemDesignState.steps;
  const total = steps.length;
  const completed = steps.filter((step) => systemDesignState.progressByStep.get(Number(step.step_no || 0))).length;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

  refs.completionBadge.textContent = `${completed} / ${total}`;
  refs.completedPill.textContent = `${completed} completed`;
  refs.progressFill.style.width = `${percent}%`;
  refs.progressText.textContent = `${percent}% complete`;

  if (!steps.length) {
    refs.stepsList.innerHTML = '<p class="text-muted text-sm">No chapter data available.</p>';
    return;
  }

  refs.stepsList.innerHTML = steps
    .map((step) => {
      const stepNo = Number(step.step_no || 0);
      const completedStep = Boolean(systemDesignState.progressByStep.get(stepNo));
      const isSaving = systemDesignState.saveInFlightByStep.has(stepNo);
      const title = escapeHtml(step.title || `Step ${stepNo}`);
      const htmlPath = String(step.local_html || "").trim();
      const hasLessonPath = Boolean(htmlPath);
      const href = hasLessonPath ? escapeAttribute(encodeURI(htmlPath)) : "#";

      return `
        <article class="system-design-step-row ${completedStep ? "is-complete" : ""}">
          <div class="system-design-step-main">
            <span class="system-design-step-index">Step ${stepNo}</span>
            ${hasLessonPath
              ? `<a class="system-design-step-link" href="${href}">${title}</a>`
              : `<span class="system-design-step-link is-disabled">${title}</span>`}
            <span class="system-design-step-status ${completedStep ? "done" : "pending"}">${isSaving ? "Saving..." : completedStep ? "Completed" : "Pending"}</span>
          </div>
          <div class="system-design-step-actions">
            <a class="btn btn-sm ${hasLessonPath ? "" : "is-disabled"}" href="${href}" ${hasLessonPath ? "" : "aria-disabled=\"true\" tabindex=\"-1\""}>Open HTML</a>
            <label class="system-design-step-check">
              <input class="sd-step-checkbox" type="checkbox" data-step-no="${stepNo}" ${completedStep ? "checked" : ""} ${isSaving ? "disabled" : ""} />
              <span>Done</span>
            </label>
          </div>
        </article>
      `;
    })
    .join("");

  refs.stepsList.querySelectorAll(".sd-step-checkbox").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const stepNo = Number(checkbox.getAttribute("data-step-no") || 0);
      if (!stepNo) return;

      toggleCompletedStep(stepNo, checkbox.checked, refs).catch(() => {
        renderStepsList(refs);
      });
    });
  });
}

async function toggleCompletedStep(stepNo, completed, refs) {
  if (systemDesignState.saveInFlightByStep.has(stepNo)) {
    return;
  }

  const previous = Boolean(systemDesignState.progressByStep.get(stepNo));
  systemDesignState.saveInFlightByStep.add(stepNo);
  systemDesignState.progressByStep.set(stepNo, completed);
  persistLocalTickMap();
  renderStepsList(refs);

  try {
    await API.updateSystemDesignProgress(stepNo, completed);
  } catch (error) {
    systemDesignState.progressByStep.set(stepNo, previous);
    persistLocalTickMap();
    alert(`Failed to update progress: ${error.message}`);
  } finally {
    systemDesignState.saveInFlightByStep.delete(stepNo);
    renderStepsList(refs);
  }
}

function readLocalTickMap(steps) {
  let raw = {};

  try {
    const text = localStorage.getItem(SYSTEM_DESIGN_LOCAL_TICKS_KEY);
    raw = text ? JSON.parse(text) : {};
  } catch (_) {
    raw = {};
  }

  const map = new Map();
  (Array.isArray(steps) ? steps : []).forEach((step) => {
    const stepNo = Number(step && step.step_no);
    if (!Number.isFinite(stepNo) || stepNo <= 0) {
      return;
    }
    map.set(stepNo, Boolean(raw[String(stepNo)]));
  });

  return map;
}

function persistLocalTickMap() {
  const payload = {};
  systemDesignState.progressByStep.forEach((completed, stepNo) => {
    if (completed) {
      payload[String(stepNo)] = true;
    }
  });

  try {
    localStorage.setItem(SYSTEM_DESIGN_LOCAL_TICKS_KEY, JSON.stringify(payload));
  } catch (_) {
    // Ignore local storage write failures.
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

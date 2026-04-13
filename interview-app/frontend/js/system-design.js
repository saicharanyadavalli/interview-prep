/**
 * system-design.js - System Design Course page logic.
 */

const systemDesignState = {
  steps: [],
  progressByStep: new Map(),
  activeStepNo: null,
  renderRequestId: 0,
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
    toggleCompleteBtn: document.getElementById("sdToggleCompleteBtn"),
    completionBadge: document.getElementById("sdCompletionBadge"),
    completedPill: document.getElementById("sdCompletedPill"),
    progressFill: document.getElementById("sdProgressFill"),
    progressText: document.getElementById("sdProgressText"),
  };

  if (Object.values(refs).some((el) => !el)) {
    return;
  }

  try {
    const [indexRes, progressRes] = await Promise.all([
      fetch("assets/system-design/course-index.json"),
      API.getSystemDesignProgress(),
    ]);

    if (!indexRes.ok) {
      throw new Error(`Failed to load course index (${indexRes.status})`);
    }

    const indexData = await indexRes.json();
    const steps = Array.isArray(indexData && indexData.steps) ? indexData.steps : [];
    systemDesignState.steps = steps;

    const progressSteps = Array.isArray(progressRes && progressRes.steps) ? progressRes.steps : [];
    systemDesignState.progressByStep = new Map(progressSteps.map((item) => [Number(item.step_no), Boolean(item.completed)]));

    renderStepsList(refs);

    const firstIncomplete = steps.find((step) => !systemDesignState.progressByStep.get(Number(step.step_no || 0)));
    const initialStep = firstIncomplete || steps[0] || null;
    if (initialStep) {
      await openStep(initialStep, refs);
      renderStepsList(refs);
    }
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
      const active = stepNo === Number(systemDesignState.activeStepNo || 0);
      return `
        <button type="button" class="system-design-step-btn ${active ? "is-active" : ""}" data-step-no="${stepNo}">
          <span class="system-design-step-index">Step ${stepNo}</span>
          <span class="system-design-step-title">${escapeHtml(step.title || `Step ${stepNo}`)}</span>
          <span class="system-design-step-status ${completedStep ? "done" : "pending"}">${completedStep ? "Completed" : "Pending"}</span>
        </button>
      `;
    })
    .join("");

  refs.stepsList.querySelectorAll(".system-design-step-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const stepNo = Number(button.getAttribute("data-step-no") || 0);
      const step = systemDesignState.steps.find((item) => Number(item.step_no || 0) === stepNo);
      if (!step) return;

      openStep(step, refs)
        .then(() => {
          renderStepsList(refs);
        })
        .catch(() => {
          renderStepsList(refs);
        });
    });
  });
}

async function openStep(step, refs) {
  const stepNo = Number(step.step_no || 0);
  if (!stepNo) return;

  systemDesignState.activeStepNo = stepNo;
  const requestId = ++systemDesignState.renderRequestId;

  const title = String(step.title || `Step ${stepNo}`).trim();
  const htmlPath = String(step.local_html || "").trim();
  const sourceUrl = String(step.source_url || "").trim();

  refs.chapterTitle.textContent = `Step ${stepNo}: ${title}`;
  refs.chapterMeta.textContent = htmlPath ? "Loading chapter content..." : "Chapter file path unavailable.";

  refs.sourceLink.href = sourceUrl || "#";
  refs.sourceLink.style.pointerEvents = sourceUrl ? "auto" : "none";
  refs.sourceLink.style.opacity = sourceUrl ? "1" : "0.5";

  if (!htmlPath) {
    refs.chapterContent.innerHTML = '<p class="text-muted">No chapter path found for this step.</p>';
  } else {
    refs.chapterContent.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading chapter...</p>';
    await renderLessonContent(htmlPath, title, refs, requestId);
  }

  const isCompleted = Boolean(systemDesignState.progressByStep.get(stepNo));
  refs.toggleCompleteBtn.disabled = false;
  refs.toggleCompleteBtn.textContent = isCompleted ? "Mark Incomplete" : "Mark Complete";

  refs.toggleCompleteBtn.onclick = async () => {
    const current = Boolean(systemDesignState.progressByStep.get(stepNo));
    const next = !current;

    refs.toggleCompleteBtn.disabled = true;
    try {
      await API.updateSystemDesignProgress(stepNo, next);
      systemDesignState.progressByStep.set(stepNo, next);
      refs.toggleCompleteBtn.textContent = next ? "Mark Incomplete" : "Mark Complete";
    } catch (error) {
      alert(`Failed to update progress: ${error.message}`);
    } finally {
      refs.toggleCompleteBtn.disabled = false;
      renderStepsList(refs);
    }
  };
}

async function renderLessonContent(htmlPath, title, refs, requestId) {
  try {
    const response = await fetch(htmlPath, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load chapter file (${response.status})`);
    }

    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const sourceArticle = doc.querySelector("article.system-design-chapter-content") || doc.querySelector("article") || doc.body;
    if (!sourceArticle) {
      throw new Error("No chapter content found in lesson file");
    }

    const lessonNode = sourceArticle.cloneNode(true);
    normalizeLessonNodeUrls(lessonNode, htmlPath);
    lessonNode.querySelectorAll("script").forEach((scriptNode) => scriptNode.remove());
    lessonNode.classList.remove("system-design-chapter-content");
    lessonNode.classList.add("system-design-inline-lesson");

    if (requestId !== systemDesignState.renderRequestId) {
      return;
    }

    refs.chapterContent.innerHTML = "";
    refs.chapterContent.appendChild(lessonNode);
    refs.chapterMeta.textContent = "Integrated chapter view loaded.";
  } catch (error) {
    if (requestId !== systemDesignState.renderRequestId) {
      return;
    }

    refs.chapterContent.innerHTML = `<iframe class="system-design-lesson-frame" src="${encodeURI(htmlPath)}" title="${escapeHtml(title)}" loading="lazy"></iframe>`;
    refs.chapterMeta.textContent = "Embedded chapter view loaded.";
  }
}

function normalizeLessonNodeUrls(rootNode, lessonPath) {
  const baseUrl = new URL(lessonPath, window.location.href);

  rootNode.querySelectorAll("img[src], source[src], iframe[src], a[href]").forEach((node) => {
    const attr = node.hasAttribute("href") ? "href" : "src";
    const value = node.getAttribute(attr);
    if (!value || isExternalResource(value)) {
      return;
    }

    const absolute = new URL(value, baseUrl);
    node.setAttribute(attr, `${absolute.pathname}${absolute.search}${absolute.hash}`);
  });

  rootNode.querySelectorAll("source[srcset], img[srcset]").forEach((node) => {
    const srcset = node.getAttribute("srcset");
    if (!srcset) return;

    const normalized = srcset
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean)
      .map((entry) => {
        const parts = entry.split(/\s+/);
        const resource = parts[0];
        if (!resource || isExternalResource(resource)) {
          return entry;
        }

        const absolute = new URL(resource, baseUrl);
        const resolved = `${absolute.pathname}${absolute.search}${absolute.hash}`;
        return [resolved, ...parts.slice(1)].join(" ").trim();
      })
      .join(", ");

    node.setAttribute("srcset", normalized);
  });
}

function isExternalResource(value) {
  const text = String(value || "").trim().toLowerCase();
  return (
    text.startsWith("http://") ||
    text.startsWith("https://") ||
    text.startsWith("data:") ||
    text.startsWith("blob:") ||
    text.startsWith("mailto:") ||
    text.startsWith("tel:") ||
    text.startsWith("javascript:")
  );
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}

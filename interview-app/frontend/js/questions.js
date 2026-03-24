/**
 * questions.js — Global All Questions catalog.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const user = await initSidebar("questions", { requireLogin: true });
  if (!user) {
    return;
  }

  const { session } = await getSession();
  if (session) {
    await syncSessionWithBackend(session.access_token);
  }

  const questionsList = document.getElementById("questionsList");
  const totalCount = document.getElementById("totalCount");
  const searchInput = document.getElementById("searchInput");
  const filterBuilderRoot = document.getElementById("filterBuilder");

  let requestSeq = 0;
  let searchDebounce = null;
  let filterDebounce = null;
  let scrollCacheDebounce = null;
  let topicsHydrated = false;
  const PAGE_SIZE = 100;
  const UI_STATE_KEY = "questionsPageUiStateV1";
  const PAGE_CACHE_KEY = "questionsPageListCacheV1";
  const CACHE_TTL_MS = 15 * 60 * 1000;

  const listState = {
    rows: [],
    total: 0,
    offset: 0,
    hasMore: true,
    isLoading: false,
  };

  function saveUiState() {
    try {
      localStorage.setItem(
        UI_STATE_KEY,
        JSON.stringify({
          search: searchInput ? String(searchInput.value || "") : "",
          ts: Date.now(),
        })
      );
    } catch (_) {
      // Ignore storage issues.
    }
  }

  function restoreUiState() {
    try {
      const raw = localStorage.getItem(UI_STATE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return;

      if (searchInput && typeof parsed.search === "string") {
        searchInput.value = parsed.search;
      }
    } catch (_) {
      // Ignore malformed state.
    }
  }

  restoreUiState();

  const filterBuilder = filterBuilderRoot
    ? new FilterBuilder(filterBuilderRoot, {
        storageKey: "questionsPageFilterBuilderV2",
        persist: true,
      })
    : null;

  function getFiltersPayload() {
    if (!filterBuilder) {
      return { match: "all", status: [], difficulty: [], topic: [] };
    }
    return filterBuilder.getQueryObject();
  }

  function deriveSolvedModeFromStatusTokens(tokens) {
    const t = Array.isArray(tokens) ? tokens.filter(Boolean) : [];
    if (t.length !== 1) return "all";

    const token = String(t[0]).trim().toLowerCase();
    if (token === "solved" || token === "!unsolved") return "solved";
    if (token === "unsolved" || token === "!solved") return "unsolved";
    return "all";
  }

  function renderInlineStatus(message) {
    if (!questionsList) return;
    const existing = document.getElementById("qListInlineStatus");
    if (existing) existing.remove();

    if (!message) return;

    const box = document.createElement("div");
    box.id = "qListInlineStatus";
    box.className = "card-flat";
    box.innerHTML = `<p class="text-muted">${escapeHtml(message)}</p>`;
    questionsList.appendChild(box);
  }

  function clearAndPrepareList() {
    if (!questionsList) return;
    questionsList.innerHTML = "";
    renderInlineStatus("Loading questions...");
  }

  function getRequestOptions(offset, limit) {
    const query = (searchInput ? searchInput.value : "").trim();
    const filters = getFiltersPayload();
    const solvedMode = deriveSolvedModeFromStatusTokens(filters.status);
    const filtersForApi = {
      ...filters,
      status: [],
    };

    return {
      q: query,
      solved: solvedMode,
      offset: offset,
      limit: limit,
      filters: filtersForApi,
    };
  }

  function getRequestCacheKey() {
    const req = getRequestOptions(0, PAGE_SIZE);
    return JSON.stringify({
      q: req.q,
      solved: req.solved,
      filters: req.filters,
    });
  }

  function savePageCache() {
    if (!listState.rows.length) return;
    try {
      sessionStorage.setItem(
        PAGE_CACHE_KEY,
        JSON.stringify({
          key: getRequestCacheKey(),
          rows: listState.rows,
          total: listState.total,
          offset: listState.offset,
          hasMore: listState.hasMore,
          scrollY: window.scrollY || 0,
          ts: Date.now(),
        })
      );
    } catch (_) {
      // Ignore storage quota errors.
    }
  }

  function restorePageCacheIfValid() {
    try {
      const raw = sessionStorage.getItem(PAGE_CACHE_KEY);
      if (!raw) return false;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return false;

      const age = Date.now() - Number(parsed.ts || 0);
      if (age > CACHE_TTL_MS) return false;

      if (String(parsed.key || "") !== getRequestCacheKey()) return false;

      const rows = Array.isArray(parsed.rows) ? parsed.rows : [];
      listState.rows = rows;
      listState.total = Number(parsed.total || rows.length || 0);
      listState.offset = Number(parsed.offset || rows.length || 0);
      listState.hasMore = Boolean(parsed.hasMore);

      if (questionsList) {
        questionsList.innerHTML = "";
      }
      hydrateTopicsFromRows(rows);
      appendRows(rows);
      updateCountBadge();

      requestAnimationFrame(() => {
        window.scrollTo(0, Number(parsed.scrollY || 0));
      });

      return true;
    } catch (_) {
      return false;
    }
  }

  function updateCountBadge() {
    if (!totalCount) return;
    if (listState.total > 0) {
      totalCount.textContent = `${listState.rows.length} / ${listState.total}`;
    } else {
      totalCount.textContent = String(listState.rows.length);
    }
  }

  function createQuestionCard(q) {
    const solved = Number(q.solved || 0) === 1;
    const solvedLabel = solved ? "Solved" : "Not Solved";
    const difficulty = titleCase(String(q.difficulty || "Unknown"));
    const company = String(q.company_display || q.company || "Unknown");

    const card = document.createElement("div");
    card.className = "q-browse-item";
    card.innerHTML = `
      <div class="q-browse-header">
        <div class="q-browse-left">
          <span class="q-browse-num">#${q.qnum || "?"}</span>
          <a class="q-browse-title q-open-link" href="solve.html?qnum=${encodeURIComponent(q.qnum || "")}">${escapeHtml(q.problem_name || "Untitled")}</a>
        </div>
        <div class="q-browse-right">
          <span class="pill ${solved ? "pill-solved" : "pill-unsolved"}">${solvedLabel}</span>
          <span class="pill pill-difficulty">${escapeHtml(difficulty)}</span>
          <span class="pill pill-company">${escapeHtml(company)}</span>
        </div>
      </div>
    `;

    card.querySelector(".q-browse-header")?.addEventListener("click", () => {
      saveUiState();
      savePageCache();
      window.location.href = `solve.html?qnum=${encodeURIComponent(q.qnum || "")}`;
    });

    return card;
  }

  function appendRows(rows) {
    if (!questionsList) return;

    const status = document.getElementById("qListInlineStatus");
    if (status) status.remove();

    if (!listState.rows.length && !rows.length) {
      questionsList.innerHTML = `
        <div class="empty-state">
          <p class="empty-icon">📋</p>
          <p>No questions found.</p>
        </div>
      `;
      return;
    }

    rows.forEach((row) => {
      questionsList.appendChild(createQuestionCard(row));
    });

    if (listState.hasMore) {
      renderInlineStatus("Scroll down to load more...");
    } else {
      renderInlineStatus("You have reached the end of the list.");
    }
  }

  function hydrateTopicsFromRows(rows) {
    const discoveredTopics = Array.from(
      new Set(
        rows
          .flatMap((row) => (Array.isArray(row.topic_tags) ? row.topic_tags : []))
          .map((item) => String(item || "").trim().toLowerCase())
          .filter(Boolean)
      )
    );
    if (filterBuilder && discoveredTopics.length && !topicsHydrated) {
      topicsHydrated = true;
      filterBuilder.setTopics(discoveredTopics);
    }
  }

  async function loadNextPage({ reset = false } = {}) {
    if (listState.isLoading) return;

    if (reset) {
      listState.rows = [];
      listState.total = 0;
      listState.offset = 0;
      listState.hasMore = true;
      clearAndPrepareList();
    }

    if (!listState.hasMore) return;

    listState.isLoading = true;
    const thisReq = ++requestSeq;

    try {
      let data;
      const req = getRequestOptions(listState.offset, PAGE_SIZE);
      try {
        data = await API.getAllQuestionsCatalogForUser(req);
      } catch (_) {
        data = await API.getAllQuestionsCatalog(req);
      }

      if (thisReq !== requestSeq) {
        return;
      }

      const rows = (data.questions || []).map((q) => ({ ...q, solved: Number(q.solved || 0) }));
      listState.total = Number(data.total || 0);
      listState.offset += rows.length;
      listState.hasMore = rows.length === PAGE_SIZE && listState.offset < listState.total;
      listState.rows = listState.rows.concat(rows);

      hydrateTopicsFromRows(rows);
      appendRows(rows);
      updateCountBadge();
      saveUiState();
      savePageCache();
    } catch (err) {
      if (reset && questionsList) {
        questionsList.innerHTML = `<p class="text-muted">Error: ${escapeHtml(err.message)}</p>`;
      } else {
        renderInlineStatus(`Error loading next page: ${escapeHtml(err.message)}`);
      }
    } finally {
      listState.isLoading = false;
    }
  }

  function resetAndLoad() {
    loadNextPage({ reset: true });
  }

  async function tryLoadMoreOnScroll() {
    if (!listState.hasMore || listState.isLoading) return;
    const scrolled = window.scrollY + window.innerHeight;
    const threshold = document.documentElement.scrollHeight - 260;
    if (scrolled >= threshold) {
      await loadNextPage({ reset: false });
    }
  }

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      saveUiState();
      if (searchDebounce) {
        clearTimeout(searchDebounce);
      }
      searchDebounce = setTimeout(() => {
        resetAndLoad();
      }, 250);
    });
  }

  if (filterBuilder) {
    filterBuilder.onChange = () => {
      if (filterDebounce) {
        clearTimeout(filterDebounce);
      }
      filterDebounce = setTimeout(() => {
        saveUiState();
        resetAndLoad();
      }, 250);
    };
  }

  window.addEventListener("scroll", () => {
    tryLoadMoreOnScroll();
    if (scrollCacheDebounce) clearTimeout(scrollCacheDebounce);
    scrollCacheDebounce = setTimeout(() => {
      savePageCache();
    }, 180);
  }, { passive: true });

  window.addEventListener("beforeunload", () => {
    saveUiState();
    savePageCache();
  });

  if (!restorePageCacheIfValid()) {
    resetAndLoad();
  }
});

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

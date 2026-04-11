/**
 * questions.js - All Questions catalog (v2 layout).
 */

document.addEventListener("DOMContentLoaded", async () => {
  const COMPANY_FILTER_OPTIONS = [
    "24*7 Innovation Labs",
    "ABCO",
    "Accenture",
    "Accolite",
    "Adobe",
    "Airtel",
    "Amazon",
    "Amdocs",
    "American Express",
    "Apple",
    "Arcesium",
    "Atlassian",
    "BankBazaar",
    "Belzabar",
    "Bloomberg",
    "Boomerang Commerce",
    "Brocade",
    "BrowserStack",
    "Cadence India",
    "Capgemini",
    "CarWale",
    "Cavisson System",
    "Cisco",
    "Citicorp",
    "Citrix",
    "Code Brew",
    "Codenation",
    "Cognizant",
    "CouponDunia",
    "D-E-Shaw",
    "Dailyhunt",
    "DE Shaw",
    "Dell",
    "Directi",
    "Drishti-Soft",
    "eBay",
    "Epic Systems",
    "Expedia",
    "Fab.com",
    "Facebook",
    "FactSet",
    "FiberLink",
    "Flipkart",
    "FreeCharge",
    "GE",
    "Goldman Sachs",
    "Google",
    "GreyOrange",
    "Grofers",
    "Groupon",
    "HCL",
    "Hike",
    "Housing.com",
    "HSBC",
    "Huawei",
    "IBM",
    "IgniteWorld",
    "Infinera",
    "InfoEdge",
    "Informatica",
    "Infosys",
    "InMobi",
    "Intel",
    "Intuit",
    "Jabong",
    "Juniper Networks",
    "JUSPAY",
    "KLA Tencor",
    "Knowlarity",
    "Komli Media",
    "Kritikal Solutions",
    "Kuliza",
    "Linkedin",
    "Lybrate",
    "Mahindra Comviva",
    "MakeMyTrip",
    "MAQ Software",
    "Media.net",
    "Medlife",
    "MetLife",
    "Microsoft",
    "Mobicip",
    "Monotype Solutions",
    "Moonfrog Labs",
    "Morgan Stanley",
    "Myntra",
    "Nagarro",
    "National Instruments",
    "nearbuy",
    "Netskope",
    "NPCI",
    "Nutanix",
    "Nvidia",
    "OATS Systems",
    "Ola Cabs",
    "One97",
    "Open Solutions",
    "Opera",
    "Oracle",
    "Oxigen Wallet",
    "OYO Rooms",
    "PayPal",
    "Paytm",
    "Payu",
    "Philips",
    "Polycom",
    "PropTiger",
    "Pubmatic",
    "Qualcomm",
    "Quikr",
    "redBus",
    "Rockstand",
    "Salesforce",
    "Samsung",
    "SAP Labs",
    "Sapient",
    "Service Now",
    "Snapdeal",
    "Sprinklr",
    "Streamoid Technologies",
    "Swiggy",
    "Synopsys",
    "Target Corporation",
    "Taxi4Sure",
    "TCS",
    "Tejas Network",
    "Teradata",
    "Tesco",
    "Times Internet",
    "TinyOwl",
    "Twitter",
    "Uber",
    "Unisys",
    "United Health Group",
    "Veritas",
    "Visa",
    "Vizury Interactive Solutions",
    "VMWare",
    "Walmart",
    "Wipro",
    "Wooker",
    "Xome",
    "Yahoo",
    "Yatra.com",
    "Yodlee Infotech",
    "Zillious",
    "Zoho",
    "Zomato",
    "Zopper",
    "Zycus",
  ];

  const user = await initSidebar("questions", { requireLogin: true });
  if (!user) {
    return;
  }

  const { session } = await getSession();
  if (session) {
    await syncSessionWithBackend(session.access_token);
  }

  const questionsList = document.getElementById("questionsList");
  const questionsScroller = document.getElementById("questionsScroller");
  const totalCount = document.getElementById("totalCount");
  const searchInput = document.getElementById("searchInput");
  const suggestionsEl = document.getElementById("searchSuggestions");
  const filterBuilderRoot = document.getElementById("filterBuilder");
  const selectedTitleEl = document.getElementById("selectedTitle");
  const selectedSummaryEl = document.getElementById("selectedSummary");
  const selectedSuccessRateEl = document.getElementById("selectedSuccessRate");
  const selectedCompaniesEl = document.getElementById("selectedCompanies");
  const addToCustomBtn = document.getElementById("addToCustomBtn");
  const addToRevisitBtn = document.getElementById("addToRevisitBtn");
  const openSolveBtn = document.getElementById("openSolveBtn");

  if (!questionsList || !searchInput || !selectedTitleEl || !selectedSummaryEl || !selectedSuccessRateEl || !selectedCompaniesEl || !openSolveBtn) {
    return;
  }

  let requestSeq = 0;
  let searchDebounce = null;
  let filterDebounce = null;
  let scrollCacheDebounce = null;
  let suggestionIndex = -1;

  const PAGE_SIZE = 100;
  const UI_STATE_KEY = "questionsPageUiStateV2";
  const PAGE_CACHE_KEY = "questionsPageListCacheV3";
  const CUSTOM_FOLDER_KEY = "questionsCustomFolderV1";
  const CACHE_TTL_MS = 15 * 60 * 1000;

  const listState = {
    rows: [],
    total: 0,
    offset: 0,
    hasMore: true,
    isLoading: false,
    selectedQnum: null,
  };

  const filterBuilder = filterBuilderRoot
    ? new FilterBuilder(filterBuilderRoot, {
        storageKey: "questionsPageFilterBuilderV3",
        persist: true,
        companies: COMPANY_FILTER_OPTIONS,
      })
    : null;

  function getFiltersPayload() {
    if (!filterBuilder) {
      return { match: "all", status: [], difficulty: [], company: [], topic: [] };
    }
    return filterBuilder.getQueryObject();
  }

  function deriveSolvedModeFromStatusTokens(tokens) {
    const safeTokens = Array.isArray(tokens) ? tokens.filter(Boolean) : [];
    if (safeTokens.length !== 1) return "all";

    const token = normalizeToken(safeTokens[0]);
    if (token === "solved" || token === "!unsolved") return "solved";
    if (token === "unsolved" || token === "!solved") return "unsolved";
    return "all";
  }

  function getRequestOptions(offset, limit) {
    const query = searchInput.value.trim();
    const filters = getFiltersPayload();
    const solvedMode = deriveSolvedModeFromStatusTokens(filters.status);
    const filtersForApi = {
      ...filters,
      status: [],
    };

    return {
      q: query,
      solved: solvedMode,
      offset,
      limit,
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

  function saveUiState() {
    try {
      localStorage.setItem(
        UI_STATE_KEY,
        JSON.stringify({
          search: searchInput.value || "",
          selectedQnum: Number(listState.selectedQnum || 0) || null,
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

      if (typeof parsed.search === "string") {
        searchInput.value = parsed.search;
      }
      if (Number.isFinite(Number(parsed.selectedQnum)) && Number(parsed.selectedQnum) > 0) {
        listState.selectedQnum = Number(parsed.selectedQnum);
      }
    } catch (_) {
      // Ignore malformed state.
    }
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
          selectedQnum: listState.selectedQnum,
          scrollerTop: questionsScroller ? questionsScroller.scrollTop : (window.scrollY || 0),
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
      if (Number.isFinite(Number(parsed.selectedQnum)) && Number(parsed.selectedQnum) > 0) {
        listState.selectedQnum = Number(parsed.selectedQnum);
      }

      questionsList.innerHTML = "";
      hydrateTopicsFromRows(rows);
      appendRows(rows);
      updateCountBadge();
      renderSearchSuggestions();

      requestAnimationFrame(() => {
        if (questionsScroller) {
          questionsScroller.scrollTop = Number(parsed.scrollerTop || 0);
        } else {
          window.scrollTo(0, Number(parsed.scrollerTop || 0));
        }
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

  function renderInlineStatus(message) {
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
    questionsList.innerHTML = "";
    renderInlineStatus("Loading questions...");
  }

  function hydrateTopicsFromRows(rows) {
    if (!filterBuilder) return;

    const discoveredTopics = Array.from(
      new Set(
        rows
          .flatMap((row) => (Array.isArray(row.topic_tags) ? row.topic_tags : []))
          .map((item) => normalizeToken(item))
          .filter(Boolean)
      )
    );

    if (discoveredTopics.length) {
      filterBuilder.setTopics(discoveredTopics);
    }
  }

  function getCompanyBadgeText(question) {
    const companies = Array.isArray(question.companies) ? question.companies.filter(Boolean) : [];
    if (companies.length <= 1) {
      return String(question.company_display || question.company || companies[0] || "General");
    }
    return `${companies[0]} +${companies.length - 1}`;
  }

  function getCompaniesPreviewText(question) {
    const companies = Array.isArray(question.companies) ? question.companies.filter(Boolean) : [];
    if (!companies.length) {
      return String(question.company_display || question.company || "General");
    }
    if (companies.length <= 4) {
      return companies.join(", ");
    }
    return `${companies.slice(0, 4).join(", ")} +${companies.length - 4} more`;
  }

  function estimateSuccessRate(question) {
    const difficulty = normalizeToken(question.difficulty);
    const baseByDifficulty = {
      easy: 82,
      medium: 71,
      hard: 59,
    };
    const base = baseByDifficulty[difficulty] || 70;
    const swing = Number(question.qnum || 0) % 11;
    const score = base + swing - 5;
    return Math.max(42, Math.min(98, score));
  }

  function buildQuestionSummary(question) {
    const statement = String(question.statement_text || "").trim();
    if (statement) {
      return shortenText(statement, 170);
    }

    const tags = Array.isArray(question.topic_tags) ? question.topic_tags.filter(Boolean) : [];
    if (tags.length) {
      return `Focus topics: ${tags.slice(0, 6).join(", ")}.`;
    }

    return "Open this question to view the full prompt, constraints, and examples.";
  }

  function getSelectedQuestion() {
    if (!Number.isFinite(Number(listState.selectedQnum))) return null;
    return listState.rows.find((row) => Number(row.qnum || 0) === Number(listState.selectedQnum || 0)) || null;
  }

  function syncSelectedVisualState() {
    questionsList.querySelectorAll(".q-browse-item").forEach((item) => {
      const itemQnum = Number(item.getAttribute("data-qnum") || 0);
      const isSelected = itemQnum > 0 && itemQnum === Number(listState.selectedQnum || 0);
      item.classList.toggle("is-selected", isSelected);
    });
  }

  function updatePreviewPanel(question) {
    if (!question) {
      selectedTitleEl.textContent = "Select a question";
      selectedSummaryEl.textContent = "Choose a question from the list to see details.";
      selectedSuccessRateEl.textContent = "--";
      selectedCompaniesEl.textContent = "--";
      openSolveBtn.setAttribute("href", "solve.html");
      if (addToCustomBtn) addToCustomBtn.disabled = true;
      if (addToRevisitBtn) addToRevisitBtn.disabled = true;
      return;
    }

    selectedTitleEl.textContent = question.problem_name || "Untitled";
    selectedSummaryEl.textContent = buildQuestionSummary(question);
    selectedSuccessRateEl.textContent = `${estimateSuccessRate(question)}%`;
    selectedCompaniesEl.textContent = getCompaniesPreviewText(question);
    openSolveBtn.setAttribute("href", `solve.html?qnum=${encodeURIComponent(question.qnum || "")}`);
    if (addToCustomBtn) addToCustomBtn.disabled = false;
    if (addToRevisitBtn) addToRevisitBtn.disabled = false;
  }

  function selectQuestion(qnum) {
    const normalized = Number(qnum || 0);
    if (!normalized) return;

    listState.selectedQnum = normalized;
    updatePreviewPanel(getSelectedQuestion());
    syncSelectedVisualState();
    saveUiState();
    savePageCache();
  }

  function createQuestionCard(question) {
    const solved = Number(question.solved || 0) === 1;
    const solvedPill = solved ? '<span class="pill pill-solved">Solved</span>' : "";
    const difficulty = titleCase(question.difficulty || "Unknown");
    const difficultyClass = `pill-difficulty-${normalizeToken(question.difficulty)}`;
    const company = getCompanyBadgeText(question);
    const successRate = estimateSuccessRate(question);

    const card = document.createElement("div");
    card.className = "q-browse-item";
    card.setAttribute("data-qnum", String(question.qnum || ""));
    card.innerHTML = `
      <div class="q-browse-header" tabindex="0" role="button" aria-label="Select question ${escapeHtml(question.problem_name || "Untitled")}">
        <div class="q-browse-left">
          <span class="q-browse-drag" aria-hidden="true"><span>::</span><span>::</span></span>
          <span class="q-browse-num">#${question.qnum || "?"}</span>
          <a class="q-browse-title q-open-link" href="solve.html?qnum=${encodeURIComponent(question.qnum || "")}">${escapeHtml(question.problem_name || "Untitled")}</a>
        </div>
        <div class="q-browse-right">
          ${solvedPill}
          <span class="pill ${difficultyClass}">${escapeHtml(difficulty)}</span>
          <span class="pill pill-company">${escapeHtml(company)}</span>
          <span class="pill pill-success">${successRate}%</span>
        </div>
      </div>
    `;

    const headerEl = card.querySelector(".q-browse-header");
    const linkEl = card.querySelector(".q-open-link");

    if (headerEl) {
      headerEl.addEventListener("click", () => {
        selectQuestion(question.qnum);
      });
      headerEl.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectQuestion(question.qnum);
        }
      });
    }

    if (linkEl) {
      linkEl.addEventListener("click", (event) => {
        event.stopPropagation();
        saveUiState();
        savePageCache();
      });
    }

    return card;
  }

  function appendRows(rows) {
    const inlineStatus = document.getElementById("qListInlineStatus");
    if (inlineStatus) inlineStatus.remove();

    if (!listState.rows.length && !rows.length) {
      questionsList.innerHTML = `
        <div class="empty-state">
          <p class="empty-icon">📋</p>
          <p>No questions found.</p>
        </div>
      `;
      updatePreviewPanel(null);
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

    const selectedExists = listState.rows.some((row) => Number(row.qnum || 0) === Number(listState.selectedQnum || 0));
    if (!selectedExists && listState.rows.length) {
      listState.selectedQnum = Number(listState.rows[0].qnum || 0) || null;
    }

    updatePreviewPanel(getSelectedQuestion());
    syncSelectedVisualState();
  }

  async function loadNextPage({ reset = false } = {}) {
    if (listState.isLoading) return;

    if (reset) {
      listState.rows = [];
      listState.total = 0;
      listState.offset = 0;
      listState.hasMore = true;
      listState.selectedQnum = null;
      clearAndPrepareList();
      updatePreviewPanel(null);
      if (questionsScroller) {
        questionsScroller.scrollTop = 0;
      }
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

      const rows = (data.questions || []).map((item) => ({
        ...item,
        solved: Number(item.solved || 0),
      }));

      listState.total = Number(data.total || 0);
      listState.offset += rows.length;
      listState.hasMore = rows.length === PAGE_SIZE && listState.offset < listState.total;
      listState.rows = listState.rows.concat(rows);

      hydrateTopicsFromRows(rows);
      appendRows(rows);
      updateCountBadge();
      renderSearchSuggestions();
      saveUiState();
      savePageCache();
    } catch (err) {
      if (reset) {
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

    if (questionsScroller) {
      const remaining = questionsScroller.scrollHeight - (questionsScroller.scrollTop + questionsScroller.clientHeight);
      if (remaining <= 190) {
        await loadNextPage({ reset: false });
      }
      return;
    }

    const scrolled = window.scrollY + window.innerHeight;
    const threshold = document.documentElement.scrollHeight - 260;
    if (scrolled >= threshold) {
      await loadNextPage({ reset: false });
    }
  }

  function findSuggestions(query) {
    const needle = normalizeToken(query);
    if (!needle || needle.length < 2) return [];

    const scored = listState.rows
      .map((row) => {
        const title = String(row.problem_name || "");
        const topic = (Array.isArray(row.topic_tags) ? row.topic_tags : []).join(" ");
        const companies = (Array.isArray(row.companies) ? row.companies : []).join(" ");
        const haystack = `${title} ${companies} ${topic} ${row.difficulty || ""}`.toLowerCase();

        const index = haystack.indexOf(needle);
        return {
          row,
          index,
          startsWithTitle: title.toLowerCase().startsWith(needle),
        };
      })
      .filter((item) => item.index >= 0)
      .sort((a, b) => {
        if (a.startsWithTitle !== b.startsWithTitle) {
          return a.startsWithTitle ? -1 : 1;
        }
        if (a.index !== b.index) {
          return a.index - b.index;
        }
        return Number(a.row.qnum || 0) - Number(b.row.qnum || 0);
      });

    return scored.slice(0, 7).map((item) => item.row);
  }

  function hideSearchSuggestions() {
    suggestionIndex = -1;
    if (!suggestionsEl) return;
    suggestionsEl.classList.add("hidden");
    suggestionsEl.innerHTML = "";
  }

  function renderSearchSuggestions() {
    if (!suggestionsEl) return;

    const query = searchInput.value.trim();
    const suggestions = findSuggestions(query);
    if (!suggestions.length) {
      hideSearchSuggestions();
      return;
    }

    suggestionsEl.innerHTML = suggestions
      .map((row, index) => {
        const company = getCompanyBadgeText(row);
        return `
          <button type="button" class="questions-suggestion-item ${index === suggestionIndex ? "is-active" : ""}" data-qnum="${Number(row.qnum || 0)}">
            <span aria-hidden="true">⌕</span>
            <span>${escapeHtml(row.problem_name || "Untitled")}</span>
            <span class="text-muted text-sm">(${escapeHtml(company)})</span>
          </button>
        `;
      })
      .join("");

    suggestionsEl.classList.remove("hidden");

    suggestionsEl.querySelectorAll(".questions-suggestion-item").forEach((item) => {
      item.addEventListener("click", () => {
        const qnum = Number(item.getAttribute("data-qnum") || 0);
        const selected = listState.rows.find((row) => Number(row.qnum || 0) === qnum);
        if (!selected) return;

        searchInput.value = selected.problem_name || "";
        hideSearchSuggestions();
        resetAndLoad();
      });
    });
  }

  function moveSuggestionCursor(direction) {
    if (!suggestionsEl || suggestionsEl.classList.contains("hidden")) return;

    const items = Array.from(suggestionsEl.querySelectorAll(".questions-suggestion-item"));
    if (!items.length) return;

    suggestionIndex += direction;
    if (suggestionIndex < 0) suggestionIndex = items.length - 1;
    if (suggestionIndex >= items.length) suggestionIndex = 0;

    items.forEach((item, index) => {
      item.classList.toggle("is-active", index === suggestionIndex);
    });
  }

  async function addCurrentSelectionToCustomFolder() {
    const selected = getSelectedQuestion();
    if (!selected) {
      showToast("Select a question first.", "warning");
      return;
    }

    try {
      const raw = localStorage.getItem(CUSTOM_FOLDER_KEY);
      const parsed = JSON.parse(raw || "[]");
      const existing = Array.isArray(parsed) ? parsed : [];
      const normalized = Array.from(new Set(existing.map((item) => Number(item || 0)).filter((value) => value > 0)));

      if (normalized.includes(Number(selected.qnum || 0))) {
        showToast("Question already in custom folder.", "info");
        return;
      }

      normalized.push(Number(selected.qnum || 0));
      localStorage.setItem(CUSTOM_FOLDER_KEY, JSON.stringify(normalized));
      showToast("Added to custom folder.", "success");
    } catch (_) {
      showToast("Unable to save custom folder entry.", "error");
    }
  }

  async function addCurrentSelectionToRevisitQueue() {
    const selected = getSelectedQuestion();
    if (!selected) {
      showToast("Select a question first.", "warning");
      return;
    }

    if (addToRevisitBtn) {
      addToRevisitBtn.disabled = true;
    }

    try {
      await API.updateProgress(selected.qnum, { revisit: true });
      showToast("Added to revisit queue.", "success");
    } catch (err) {
      showToast(`Failed to add revisit: ${err.message}`, "error");
    } finally {
      if (addToRevisitBtn) {
        addToRevisitBtn.disabled = false;
      }
    }
  }

  function showToast(message, type = "info") {
    let toast = document.getElementById("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.className = `toast toast-${type} toast-show`;
    setTimeout(() => {
      toast.classList.remove("toast-show");
    }, 2600);
  }

  restoreUiState();
  updatePreviewPanel(getSelectedQuestion());

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      saveUiState();
      renderSearchSuggestions();
      if (searchDebounce) {
        clearTimeout(searchDebounce);
      }
      searchDebounce = setTimeout(() => {
        resetAndLoad();
      }, 260);
    });

    searchInput.addEventListener("focus", () => {
      renderSearchSuggestions();
    });

    searchInput.addEventListener("keydown", (event) => {
      if (!suggestionsEl || suggestionsEl.classList.contains("hidden")) return;

      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveSuggestionCursor(1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveSuggestionCursor(-1);
      } else if (event.key === "Escape") {
        hideSearchSuggestions();
      } else if (event.key === "Enter") {
        const active = suggestionsEl.querySelector(".questions-suggestion-item.is-active");
        if (active) {
          event.preventDefault();
          active.click();
        }
      }
    });
  }

  document.addEventListener("click", (event) => {
    if (!suggestionsEl) return;
    const target = event.target;
    if (!(target instanceof Element)) return;

    if (target.closest(".questions-search-wrap")) return;
    hideSearchSuggestions();
  });

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

  if (addToCustomBtn) {
    addToCustomBtn.addEventListener("click", () => {
      addCurrentSelectionToCustomFolder();
    });
  }

  if (addToRevisitBtn) {
    addToRevisitBtn.addEventListener("click", () => {
      addCurrentSelectionToRevisitQueue();
    });
  }

  if (questionsScroller) {
    questionsScroller.addEventListener(
      "scroll",
      () => {
        tryLoadMoreOnScroll();
        if (scrollCacheDebounce) clearTimeout(scrollCacheDebounce);
        scrollCacheDebounce = setTimeout(() => {
          savePageCache();
        }, 180);
      },
      { passive: true }
    );
  } else {
    window.addEventListener(
      "scroll",
      () => {
        tryLoadMoreOnScroll();
        if (scrollCacheDebounce) clearTimeout(scrollCacheDebounce);
        scrollCacheDebounce = setTimeout(() => {
          savePageCache();
        }, 180);
      },
      { passive: true }
    );
  }

  window.addEventListener("beforeunload", () => {
    saveUiState();
    savePageCache();
  });

  if (!restorePageCacheIfValid()) {
    resetAndLoad();
  }
});

function normalizeToken(value) {
  return String(value || "").trim().toLowerCase();
}

function titleCase(value) {
  return String(value || "")
    .toLowerCase()
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function shortenText(value, maxLength) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 3))}...`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

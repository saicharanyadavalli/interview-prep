/**
 * api.js — Backend API wrapper for the Interview Practice Platform.
 *
 * All fetch calls to the FastAPI backend go through this module.
 * The access token is automatically included in Authorization headers
 * for authenticated endpoints.
 */

const API = {
  _PROFILE_CACHE_KEY: "ipp_profile_cache_v1",

  getCachedProfile(maxAgeMs = 24 * 60 * 60 * 1000) {
    try {
      const raw = localStorage.getItem(this._PROFILE_CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || !parsed.data) return null;

      const ts = Number(parsed.ts || 0);
      if (maxAgeMs > 0 && Date.now() - ts > maxAgeMs) {
        return null;
      }
      return parsed.data;
    } catch (_) {
      return null;
    }
  },

  setCachedProfile(profile) {
    if (!profile || typeof profile !== "object") return;
    try {
      localStorage.setItem(
        this._PROFILE_CACHE_KEY,
        JSON.stringify({ ts: Date.now(), data: profile })
      );
    } catch (_) {
      // Ignore storage quota issues.
    }
  },

  clearCachedProfile() {
    try {
      localStorage.removeItem(this._PROFILE_CACHE_KEY);
    } catch (_) {
      // Ignore localStorage errors.
    }
  },

  _appendQuestionFilters(params, filters = {}) {
    if (!filters || typeof filters !== "object") return;

    const appendValue = (key, value) => {
      const text = String(value || "").trim();
      if (text) params.append(key, text);
    };

    const pushTokenized = (key, values = []) => {
      const tokens = (Array.isArray(values) ? values : [values])
        .map((item) => String(item || "").trim())
        .filter(Boolean);
      if (tokens.length) {
        params.set(key, tokens.join(","));
      }
    };

    if (filters.match === "all" || filters.match === "any") {
      appendValue("match", filters.match);
    }

    pushTokenized("status", filters.status);
    pushTokenized("difficulty", filters.difficulty);
    pushTokenized("company", filters.company);
    pushTokenized("topic", filters.topic);
  },

  /**
   * Generic fetch wrapper. Adds auth header if token is available.
   */
  async _fetch(path, options = {}) {
    const url = CONFIG.API_BASE_URL + path;
    const headers = options.headers || {};
    const isFormDataBody = typeof FormData !== "undefined" && options.body instanceof FormData;
    if (!isFormDataBody) {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
    }

    // Try to add auth token
    try {
      const token = await getAccessToken();
      if (token) {
        headers["Authorization"] = "Bearer " + token;
      }
    } catch (_) {
      // Auth not available — continue without token
    }

    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      if (!window.location.pathname.toLowerCase().endsWith("/login.html")) {
        window.location.href = "login.html";
      }
      throw new Error("Authentication required. Please sign in again.");
    }

    if (!response.ok) {
      const detail = await response.text().catch(() => "Unknown error");
      throw new Error(`API ${response.status}: ${detail}`);
    }

    return response.json();
  },

  // ---- Questions ----

  async getCompanies() {
    return this._fetch("/questions/companies");
  },

  async getAllQuestions(company, difficulty, filters = {}) {
    const params = new URLSearchParams();
    params.set("company", String(company));
    params.set("difficulty", String(difficulty));
    this._appendQuestionFilters(params, filters);
    return this._fetch(`/questions/all?${params.toString()}`);
  },

  async getAllQuestionsCatalog(options = {}) {
    const params = new URLSearchParams();
    if (options.q) params.set("q", String(options.q));
    this._appendQuestionFilters(params, options.filters || {});
    if (Number.isFinite(Number(options.offset))) params.set("offset", String(Number(options.offset)));
    if (Number.isFinite(Number(options.limit))) params.set("limit", String(Number(options.limit)));
    const query = params.toString();
    return this._fetch(`/questions/catalog${query ? `?${query}` : ""}`);
  },

  async getAllQuestionsCatalogForUser(options = {}) {
    const params = new URLSearchParams();
    if (options.q) params.set("q", String(options.q));
    if (options.solved) params.set("solved", String(options.solved));
    this._appendQuestionFilters(params, options.filters || {});
    if (Number.isFinite(Number(options.offset))) params.set("offset", String(Number(options.offset)));
    if (Number.isFinite(Number(options.limit))) params.set("limit", String(Number(options.limit)));
    const query = params.toString();
    return this._fetch(`/questions/catalog/user${query ? `?${query}` : ""}`);
  },

  async getQuestionByQnum(qnum) {
    return this._fetch(`/questions/by-qnum/${encodeURIComponent(qnum)}`);
  },

  // ---- AI Assistant ----

  async askAssistant(interviewQuestion, userDoubt, conversationHistory = []) {
    return this._fetch("/assistant/ask", {
      method: "POST",
      body: JSON.stringify({
        interview_question: interviewQuestion,
        user_doubt: userDoubt,
        conversation_history: conversationHistory,
      }),
    });
  },

  // ---- Progress ----

  async updateProgress(questionRef, statusOrPayload) {
    const isNum = Number.isFinite(Number(questionRef)) && Number(questionRef) > 0;
    const payload = typeof statusOrPayload === "string"
      ? { status: statusOrPayload }
      : { ...(statusOrPayload || {}) };

    return this._fetch("/progress/update", {
      method: "POST",
      body: JSON.stringify({
        qnum: isNum ? Number(questionRef) : undefined,
        question_id: isNum ? undefined : String(questionRef || ""),
        ...payload,
      }),
    });
  },

  async getUserProgress() {
    return this._fetch("/progress/user");
  },

  async getProgressStatus(qnum) {
    return this._fetch(`/progress/status/${encodeURIComponent(qnum)}`);
  },

  async clearProgress(qnum) {
    return this._fetch(`/progress/${encodeURIComponent(qnum)}`, {
      method: "DELETE",
    });
  },

  // ---- Profile ----

  async getMyProfile(options = {}) {
    const preferCache = options.preferCache !== false;
    const maxAgeMs = Number.isFinite(Number(options.maxAgeMs))
      ? Number(options.maxAgeMs)
      : (24 * 60 * 60 * 1000);

    if (preferCache) {
      const cached = this.getCachedProfile(maxAgeMs);
      if (cached) {
        return cached;
      }
    }

    const profile = await this._fetch("/profile/me");
    this.setCachedProfile(profile);
    return profile;
  },

  async updateMyProfile(payload) {
    const updated = await this._fetch("/profile/me", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    this.setCachedProfile(updated);
    return updated;
  },

  async uploadProfileAvatar(file) {
    const formData = new FormData();
    formData.append("file", file);
    const result = await this._fetch("/profile/avatar/upload", {
      method: "POST",
      headers: {},
      body: formData,
    });
    if (result && result.avatar_url) {
      const cached = this.getCachedProfile(0) || {};
      this.setCachedProfile({ ...cached, avatar_url: result.avatar_url });
    }
    return result;
  },

  // ---- Revisit Queue ----

  async getRevisitQueue() {
    return this._fetch("/revisit");
  },

  async removeFromRevisit(qnum) {
    return this._fetch(`/revisit/${encodeURIComponent(qnum)}`, {
      method: "DELETE",
    });
  },

  // ---- Comments ----

  async addComment(questionRef, commentText) {
    const isNum = Number.isFinite(Number(questionRef)) && Number(questionRef) > 0;
    return this._fetch("/comments/add", {
      method: "POST",
      body: JSON.stringify({
        qnum: isNum ? Number(questionRef) : undefined,
        question_id: isNum ? undefined : String(questionRef || ""),
        comment_text: commentText,
      }),
    });
  },

  async getComments(qnum) {
    return this._fetch(`/comments/${encodeURIComponent(qnum)}`);
  },
};

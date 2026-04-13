/**
 * api.js — Backend API wrapper for the Interview Practice Platform.
 *
 * All fetch calls to the FastAPI backend go through this module.
 * The access token is automatically included in Authorization headers
 * for authenticated endpoints.
 */

const API = {
  _PROFILE_CACHE_KEY: "ipp_profile_cache_v1",
  _SYSTEM_DESIGN_PROGRESS_CACHE_KEY: "ipp_system_design_progress_v1",
  _SYSTEM_DESIGN_STEP_COUNT: 30,
  _SYSTEM_DESIGN_QNUM_BASE: 900000,

  _extractApiStatusCode(error) {
    const message = String((error && error.message) || "");
    const match = message.match(/^API\s+(\d+):/i);
    return match ? Number(match[1]) : null;
  },

  _isApiNotFound(error) {
    return this._extractApiStatusCode(error) === 404;
  },

  _stepToSystemDesignQnum(stepNo) {
    return this._SYSTEM_DESIGN_QNUM_BASE + Number(stepNo || 0);
  },

  _readSystemDesignProgressCache() {
    try {
      const raw = localStorage.getItem(this._SYSTEM_DESIGN_PROGRESS_CACHE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {};
      const data = parsed.data && typeof parsed.data === "object" ? parsed.data : {};
      return data;
    } catch (_) {
      return {};
    }
  },

  _writeSystemDesignProgressCache(data) {
    try {
      localStorage.setItem(
        this._SYSTEM_DESIGN_PROGRESS_CACHE_KEY,
        JSON.stringify({ ts: Date.now(), data: data || {} })
      );
    } catch (_) {
      // Ignore storage quota issues.
    }
  },

  _cacheSystemDesignProgressResponse(response) {
    if (!response || !Array.isArray(response.steps)) return;
    const map = {};
    response.steps.forEach((step) => {
      const stepNo = Number(step && step.step_no);
      if (!Number.isFinite(stepNo) || stepNo <= 0) return;
      map[String(stepNo)] = {
        completed: Boolean(step.completed),
        updated_at: step.updated_at || null,
      };
    });
    this._writeSystemDesignProgressCache(map);
  },

  _buildSystemDesignProgressFromMap(progressMap = {}) {
    const steps = [];
    let completedSteps = 0;

    for (let stepNo = 1; stepNo <= this._SYSTEM_DESIGN_STEP_COUNT; stepNo += 1) {
      const entry = progressMap[String(stepNo)] || {};
      const completed = Boolean(entry.completed);
      if (completed) completedSteps += 1;

      steps.push({
        step_no: stepNo,
        title: `Step ${stepNo}`,
        completed,
        updated_at: entry.updated_at || null,
      });
    }

    return {
      total_steps: this._SYSTEM_DESIGN_STEP_COUNT,
      completed_steps: completedSteps,
      completion_percent: Math.round((completedSteps / this._SYSTEM_DESIGN_STEP_COUNT) * 100),
      steps,
      source: "legacy-fallback",
    };
  },

  async _loadLegacySystemDesignProgressMap() {
    const cached = this._readSystemDesignProgressCache();
    const nextMap = { ...cached };

    const statuses = await Promise.all(
      Array.from({ length: this._SYSTEM_DESIGN_STEP_COUNT }, async (_, index) => {
        const stepNo = index + 1;
        const qnum = this._stepToSystemDesignQnum(stepNo);
        try {
          const status = await this.getProgressStatus(qnum);
          return { stepNo, status };
        } catch (_) {
          return null;
        }
      })
    );

    let hasRemoteData = false;
    statuses.forEach((item) => {
      if (!item || !item.status) return;
      const rawSolved = item.status.is_solved;
      if (rawSolved === null || rawSolved === undefined) return;

      hasRemoteData = true;
      nextMap[String(item.stepNo)] = {
        completed: rawSolved === true,
        updated_at: new Date().toISOString(),
      };
    });

    if (hasRemoteData) {
      this._writeSystemDesignProgressCache(nextMap);
    }

    return nextMap;
  },

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
      if (!window.location.pathname.toLowerCase().endsWith("/index.html")) {
        window.location.href = "index.html";
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
    if (options.solved) params.set("solved", String(options.solved));
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

  async updateProgress(questionRef, progressPayload) {
    const isNum = Number.isFinite(Number(questionRef)) && Number(questionRef) > 0;
    const payload = { ...(progressPayload || {}) };

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

  async getSystemDesignProgress() {
    try {
      const response = await this._fetch("/system-design/progress");
      this._cacheSystemDesignProgressResponse(response);
      return response;
    } catch (error) {
      if (!this._isApiNotFound(error)) {
        throw error;
      }

      const fallbackMap = await this._loadLegacySystemDesignProgressMap();
      return this._buildSystemDesignProgressFromMap(fallbackMap);
    }
  },

  async updateSystemDesignProgress(stepNo, completed) {
    const numericStepNo = Number(stepNo);
    if (!Number.isFinite(numericStepNo) || numericStepNo < 1 || numericStepNo > this._SYSTEM_DESIGN_STEP_COUNT) {
      throw new Error(`Invalid step number: ${stepNo}`);
    }

    const safeStepNo = Math.round(numericStepNo);
    const payload = {
      step_no: safeStepNo,
      completed: Boolean(completed),
    };

    try {
      const response = await this._fetch("/system-design/progress", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      const cache = this._readSystemDesignProgressCache();
      cache[String(safeStepNo)] = {
        completed: Boolean(completed),
        updated_at: response && response.updated_at ? response.updated_at : new Date().toISOString(),
      };
      this._writeSystemDesignProgressCache(cache);

      return response;
    } catch (error) {
      if (!this._isApiNotFound(error)) {
        throw error;
      }

      const qnum = this._stepToSystemDesignQnum(safeStepNo);
      await this.updateProgress(qnum, {
        is_solved: Boolean(completed),
        revisit: false,
      });

      const cache = this._readSystemDesignProgressCache();
      const now = new Date().toISOString();
      cache[String(safeStepNo)] = {
        completed: Boolean(completed),
        updated_at: now,
      };
      this._writeSystemDesignProgressCache(cache);

      return {
        step_no: safeStepNo,
        title: `Step ${safeStepNo}`,
        completed: Boolean(completed),
        updated_at: now,
      };
    }
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

  async deleteComment(commentId) {
    return this._fetch(`/comments/${encodeURIComponent(commentId)}`, {
      method: "DELETE",
    });
  },
};

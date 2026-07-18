import { CONFIG } from "./config";
import { getSupabase } from "./supabase";

export const API = {
  _PROFILE_CACHE_KEY: "ipp_profile_cache_v1",
  _activeRequests: new Map<string, Promise<any>>(),

  getCachedProfile(maxAgeMs = 24 * 60 * 60 * 1000) {
    if (typeof window === "undefined") return null;
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

  setCachedProfile(profile: any) {
    if (typeof window === "undefined") return;
    if (!profile || typeof profile !== "object") return;
    try {
      localStorage.setItem(
        this._PROFILE_CACHE_KEY,
        JSON.stringify({ ts: Date.now(), data: profile })
      );
    } catch (_) {}
  },

  clearCachedProfile() {
    if (typeof window === "undefined") return;
    try {
      localStorage.removeItem(this._PROFILE_CACHE_KEY);
    } catch (_) {}
  },

  _appendQuestionFilters(params: URLSearchParams, filters: any = {}) {
    if (!filters || typeof filters !== "object") return;

    const appendValue = (key: string, value: any) => {
      const text = String(value || "").trim();
      if (text) params.append(key, text);
    };

    const pushTokenized = (key: string, values: any = []) => {
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

  async _getAccessToken() {
    const sb = getSupabase();
    if (!sb) return null;
    const { data } = await sb.auth.getSession();
    return data?.session?.access_token || null;
  },
  async _fetch(path: string, options: RequestInit = {}) {
    const url = CONFIG.API_BASE_URL + path;
    const isGet = !options.method || options.method.toUpperCase() === "GET";
    const cacheKey = isGet ? url : null;

    if (cacheKey && this._activeRequests.has(cacheKey)) {
      return this._activeRequests.get(cacheKey);
    }

    const fetchPromise = (async () => {
      const headers: Record<string, string> = (options.headers as Record<string, string>) || {};
      const isFormDataBody = typeof FormData !== "undefined" && options.body instanceof FormData;
      
      if (!isFormDataBody) {
        headers["Content-Type"] = headers["Content-Type"] || "application/json";
      }

      try {
        const token = await this._getAccessToken();
        if (token) {
          headers["Authorization"] = "Bearer " + token;
        }
      } catch (_) {}

      const response = await fetch(url, { ...options, headers });

      if (response.status === 401) {
        if (typeof window !== "undefined") {
          if (!window.location.pathname.toLowerCase().endsWith("/login") && window.location.pathname !== "/") {
            window.location.href = "/login";
          }
        }
        throw new Error("Authentication required. Please sign in again.");
      }

      if (!response.ok) {
        const detail = await response.text().catch(() => "Unknown error");
        throw new Error(`API ${response.status}: ${detail}`);
      }

      return response.json();
    })();

    if (cacheKey) {
      this._activeRequests.set(cacheKey, fetchPromise);
      fetchPromise.finally(() => this._activeRequests.delete(cacheKey));
    }

    return fetchPromise;
  },

  async getCompanies() {
    return this._fetch("/questions/companies");
  },

  async getAllQuestions(company: string, difficulty: string, filters: any = {}) {
    const params = new URLSearchParams();
    params.set("company", String(company));
    params.set("difficulty", String(difficulty));
    this._appendQuestionFilters(params, filters);
    return this._fetch(`/questions/all?${params.toString()}`);
  },

  async getAllQuestionsCatalog(options: any = {}) {
    const params = new URLSearchParams();
    if (options.q) params.set("q", String(options.q));
    if (options.solved) params.set("solved", String(options.solved));
    this._appendQuestionFilters(params, options.filters || {});
    if (Number.isFinite(Number(options.offset))) params.set("offset", String(Number(options.offset)));
    if (Number.isFinite(Number(options.limit))) params.set("limit", String(Number(options.limit)));
    const qString = params.toString();
    return this._fetch(`/questions/catalog${qString ? "?" + qString : ""}`);
  },

  async getAllQuestionsCatalogForUser(options: any = {}) {
    const params = new URLSearchParams();
    if (options.q) params.set("q", String(options.q));
    if (options.solved) params.set("solved", String(options.solved));
    this._appendQuestionFilters(params, options.filters || {});
    if (Number.isFinite(Number(options.offset))) params.set("offset", String(Number(options.offset)));
    if (Number.isFinite(Number(options.limit))) params.set("limit", String(Number(options.limit)));
    const query = params.toString();
    return this._fetch(`/questions/catalog/user${query ? `?${query}` : ""}`);
  },

  async getQuestionByQnum(qnum: string) {
    return this._fetch(`/questions/by-qnum/${encodeURIComponent(qnum)}`);
  },

  async askAssistantStream(interviewQuestion: any, userDoubt: string, conversationHistory: any[] = []) {
    const url = CONFIG.API_BASE_URL + "/assistant/ask";
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    try {
      const token = await this._getAccessToken();
      if (token) headers["Authorization"] = "Bearer " + token;
    } catch (_) {}

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({
        interview_question: interviewQuestion,
        user_doubt: userDoubt,
        conversation_history: conversationHistory,
      }),
    });

    if (response.status === 401) {
      if (typeof window !== "undefined" && !window.location.pathname.toLowerCase().endsWith("/login") && window.location.pathname !== "/") {
        window.location.href = "/login";
      }
      throw new Error("Authentication required. Please sign in again.");
    }
    if (!response.ok) {
      const detail = await response.text().catch(() => "Unknown error");
      throw new Error(`API ${response.status}: ${detail}`);
    }
    if (!response.body) throw new Error("No response body");
    return response.body;
  },

  async askAssistant(interviewQuestion: any, userDoubt: string, conversationHistory: any[] = []) {
    return this._fetch("/assistant/ask", {
      method: "POST",
      body: JSON.stringify({
        interview_question: interviewQuestion,
        user_doubt: userDoubt,
        conversation_history: conversationHistory,
      }),
    });
  },

  async updateProgress(questionRef: any, progressPayload: any) {
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

  async getUserProgress(summaryOnly?: boolean) {
    return this._fetch(`/progress/user${summaryOnly ? "?summary_only=true" : ""}`);
  },

  async getProgressStatus(qnum: string) {
    return this._fetch(`/progress/status/${encodeURIComponent(qnum)}`);
  },

  async clearProgress(qnum: string) {
    return this._fetch(`/progress/${encodeURIComponent(qnum)}`, {
      method: "DELETE",
    });
  },

  async getMyProfile(options: any = {}) {
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

  async updateMyProfile(payload: any) {
    const updated = await this._fetch("/profile/me", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    this.setCachedProfile(updated);
    return updated;
  },

  async uploadProfileAvatar(file: File) {
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

  async getRevisitQueue() {
    return this._fetch("/revisit");
  },

  async removeFromRevisit(qnum: string) {
    return this._fetch(`/revisit/${encodeURIComponent(qnum)}`, {
      method: "DELETE",
    });
  },

  async addComment(questionRef: any, commentText: string) {
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

  async getComments(qnum: string) {
    return this._fetch(`/comments/${encodeURIComponent(qnum)}`);
  },

  async deleteComment(commentId: string) {
    return this._fetch(`/comments/${encodeURIComponent(commentId)}`, {
      method: "DELETE",
    });
  },

  async getLearningTrackLesson(trackId: string, stepNo: number) {
    return this._fetch(`/learning-tracks/${encodeURIComponent(trackId)}/lessons/${stepNo}`);
  },

  async getLearningTracks() {
    return this._fetch("/learning-tracks");
  },

  async getLearningTrackProgress(trackId: string) {
    return this._fetch(`/learning-tracks/${encodeURIComponent(trackId)}/progress`);
  },

  async updateLearningTrackProgress(trackId: string, stepNo: number, completed: boolean) {
    return this._fetch(`/learning-tracks/${encodeURIComponent(trackId)}/progress`, {
      method: "POST",
      body: JSON.stringify({ step_no: stepNo, completed }),
    });
  },
};


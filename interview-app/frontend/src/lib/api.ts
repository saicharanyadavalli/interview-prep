import { CONFIG } from "./config";

export const COURSE_CATALOG_DATA: Record<
  string,
  { title: string; description: string; total_lessons: number }
> = {
  "system-design": {
    title: "System Design Fundamentals",
    description: "Master large-scale distributed system design principles, microservices, and interview patterns with 30 in-depth architectural breakdowns.",
    total_lessons: 30,
  },
  "genai-system-design": {
    title: "Generative AI System Design",
    description: "Design cutting-edge GenAI architectures including ChatGPT chatbots, RAG pipelines, Diffusion models, and Multimodal video synthesis.",
    total_lessons: 11,
  },
  "ml-system-design": {
    title: "Machine Learning System Design",
    description: "Architect real-world ML systems including Visual Search, YouTube Video Recommendations, and Real-time Ad Click Prediction.",
    total_lessons: 11,
  },
  "mobile-system-design": {
    title: "Mobile System Design",
    description: "Master end-to-end mobile architecture for high-performance apps, offline caching, push notifications, and real-time news feeds.",
    total_lessons: 11,
  },
  "object-oriented-design": {
    title: "Object-Oriented Design (OOD)",
    description: "Learn design patterns, SOLID principles, and complete class-diagram implementations for classic interview problems like Parking Lot and Elevator.",
    total_lessons: 14,
  },
  "sql-course": {
    title: "SQL Practice Course",
    description: "Master SQL queries step-by-step with interactive sql.js practice tables and exercises.",
    total_lessons: 21,
  },
};

export const API = {
  _PROFILE_CACHE_KEY: "ipp_profile_cache_v1",
  _activeRequests: new Map<string, Promise<any>>(),

  getCachedProfile(maxAgeMs = 24 * 60 * 60 * 1000, expectedUserId?: string) {
    if (typeof window === "undefined") return null;
    try {
      const raw = localStorage.getItem(this._PROFILE_CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || !parsed.data) return null;

      // If an expected user ID is provided, verify ownership to prevent account-bleed
      if (expectedUserId && parsed.userId && parsed.userId !== expectedUserId) {
        return null;
      }

      const ts = Number(parsed.ts || 0);
      if (maxAgeMs > 0 && Date.now() - ts > maxAgeMs) {
        return null;
      }
      return parsed.data;
    } catch (_) {
      return null;
    }
  },

  setCachedProfile(profile: any, userId?: string) {
    if (typeof window === "undefined") return;
    if (!profile || typeof profile !== "object") return;
    try {
      const targetUserId = userId || profile.id || "";
      localStorage.setItem(
        this._PROFILE_CACHE_KEY,
        JSON.stringify({ ts: Date.now(), userId: targetUserId, data: profile })
      );
      // Dispatch a window event so all reactive components update immediately
      window.dispatchEvent(
        new CustomEvent("ipp_profile_updated", { detail: profile })
      );
    } catch (_) {}
  },

  clearCachedProfile() {
    if (typeof window === "undefined") return;
    try {
      localStorage.removeItem(this._PROFILE_CACHE_KEY);
      window.dispatchEvent(
        new CustomEvent("ipp_profile_updated", { detail: null })
      );
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
    // In Cognito architecture with HttpOnly cookies, requests to /api/backend automatically forward
    // cookies, but for direct cross-origin calls or non-HttpOnly fallbacks, inspect document.cookie:
    if (typeof document !== "undefined") {
      try {
        const cookies = document.cookie.split(";");
        for (const c of cookies) {
          const trimmed = c.trim();
          if (trimmed.startsWith("cognito_access_token=")) {
            const rawVal = trimmed.split("=").slice(1).join("=");
            if (rawVal) return decodeURIComponent(rawVal);
          }
        }
      } catch (_) {}
    }
    return null;
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
        // Return null gracefully - don't redirect to /login as this causes an
        // infinite loop when the backend is down/restarting but the user IS
        // authenticated via Supabase. The UI will show empty/error states instead.
        return null;
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

  async _fetchOptional(path: string, options: RequestInit = {}) {
    try {
      return await this._fetch(path, options);
    } catch (err: any) {
      if (String(err?.message || "").startsWith("API 404:")) {
        return null;
      }
      throw err;
    }
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
    let res: any = null;
    try {
      res = await this._fetch(`/progress/user${summaryOnly ? "?summary_only=true" : ""}`);
    } catch (_) {}

    if (res && res.stats && typeof res.stats.total_attempted === "number") {
      return res;
    }

    return res || { stats: { total_attempted: 0, solved_count: 0, revisit_count: 0, current_streak: 0 }, recent: [] };
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
    const expectedUserId = options.userId;

    if (preferCache) {
      const cached = this.getCachedProfile(maxAgeMs, expectedUserId);
      if (cached && cached.username) {
        return cached;
      }
    }

    let profile: any = null;
    try {
      profile = await this._fetch("/profile/me");
    } catch (_) {}

    if (profile) {
      this.setCachedProfile(profile, profile.id);
    }
    return profile || { id: "", email: "", username: "", name: "", phone: "", avatar_url: "" };
  },

  async updateMyProfile(payload: any) {
    const updated = await this._fetch("/profile/me", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    if (updated) {
      this.setCachedProfile(updated, updated.id);
    }
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
      const updated = { ...cached, avatar_url: result.avatar_url };
      this.setCachedProfile(updated, updated.id);
    }
    return result;
  },

  async resetUserProgress(): Promise<{ success: boolean; message: string; stats?: any }> {
    const res = await this._fetch("/profile/reset-progress", {
      method: "POST",
    });
    if (typeof window !== "undefined") {
      try {
        localStorage.removeItem("questionsPageUiState");
        window.dispatchEvent(new CustomEvent("ipp_progress_updated"));
      } catch (_) {}
    }
    return res;
  },

  async deleteUserAccount(): Promise<{ success: boolean; message: string }> {
    const res = await this._fetch("/profile/account", {
      method: "DELETE",
      body: JSON.stringify({ confirm: true }),
    });
    if (typeof window !== "undefined") {
      try {
        this.clearCachedProfile();
        localStorage.removeItem("questionsPageUiState");
        localStorage.removeItem("questionsCustomFolderV1");
        sessionStorage.clear();
      } catch (_) {}
    }
    return res;
  },

  async getRevisitQueue() {
    return this._fetch("/revisit");
  },

  async removeFromRevisit(qnum: string) {
    return this._fetch(`/revisit/${encodeURIComponent(qnum)}`, {
      method: "DELETE",
    });
  },

  async getCustomFolders() {
    return this._fetch("/progress/folders");
  },

  async createCustomFolder(name: string, qnums: number[] = []) {
    return this._fetch("/progress/folders", {
      method: "POST",
      body: JSON.stringify({ name, qnums }),
    });
  },

  async addQuestionToFolder(folderName: string, qnum: number) {
    return this._fetch("/progress/folders/add-question", {
      method: "POST",
      body: JSON.stringify({ folder_name: folderName, qnum }),
    });
  },

  async removeQuestionFromFolder(folderName: string, qnum: number) {
    return this._fetch("/progress/folders/remove-question", {
      method: "POST",
      body: JSON.stringify({ folder_name: folderName, qnum }),
    });
  },

  async deleteCustomFolder(folderName: string) {
    return this._fetch(`/progress/folders/${encodeURIComponent(folderName)}`, {
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

  // --- Courses API Endpoints ---
  async getCourses(): Promise<CourseSummary[]> {
    const defaultCatalog: CourseSummary[] = [
      {
        id: "system-design",
        slug: "system-design",
        title: COURSE_CATALOG_DATA["system-design"].title,
        description: COURSE_CATALOG_DATA["system-design"].description,
        total_lessons: COURSE_CATALOG_DATA["system-design"].total_lessons,
        completed_lessons: 0,
        progress_percentage: 0,
      },
      {
        id: "genai-system-design",
        slug: "genai-system-design",
        title: COURSE_CATALOG_DATA["genai-system-design"].title,
        description: COURSE_CATALOG_DATA["genai-system-design"].description,
        total_lessons: COURSE_CATALOG_DATA["genai-system-design"].total_lessons,
        completed_lessons: 0,
        progress_percentage: 0,
      },
      {
        id: "ml-system-design",
        slug: "ml-system-design",
        title: COURSE_CATALOG_DATA["ml-system-design"].title,
        description: COURSE_CATALOG_DATA["ml-system-design"].description,
        total_lessons: COURSE_CATALOG_DATA["ml-system-design"].total_lessons,
        completed_lessons: 0,
        progress_percentage: 0,
      },
      {
        id: "mobile-system-design",
        slug: "mobile-system-design",
        title: COURSE_CATALOG_DATA["mobile-system-design"].title,
        description: COURSE_CATALOG_DATA["mobile-system-design"].description,
        total_lessons: COURSE_CATALOG_DATA["mobile-system-design"].total_lessons,
        completed_lessons: 0,
        progress_percentage: 0,
      },
      {
        id: "object-oriented-design",
        slug: "object-oriented-design",
        title: COURSE_CATALOG_DATA["object-oriented-design"].title,
        description: COURSE_CATALOG_DATA["object-oriented-design"].description,
        total_lessons: COURSE_CATALOG_DATA["object-oriented-design"].total_lessons,
        completed_lessons: 0,
        progress_percentage: 0,
      },
      {
        id: "sql-course",
        slug: "sql-course",
        title: COURSE_CATALOG_DATA["sql-course"].title,
        description: COURSE_CATALOG_DATA["sql-course"].description,
        total_lessons: COURSE_CATALOG_DATA["sql-course"].total_lessons,
        completed_lessons: 0,
        progress_percentage: 0,
      },
    ];

    try {
      const data = await this._fetchOptional("/courses");
      if (Array.isArray(data) && data.length >= 6) {
        return data.map((c) => {
          const canonical = COURSE_CATALOG_DATA[c.slug];
          return {
            ...c,
            title: canonical?.title || c.title,
            description: canonical?.description || c.description,
            total_lessons: canonical?.total_lessons || c.total_lessons,
          };
        });
      }
      if (Array.isArray(data) && data.length > 0) {
        const map = new Map<string, CourseSummary>();
        defaultCatalog.forEach((c) => map.set(c.slug, c));
        data.forEach((c) => {
          if (c && c.slug) {
            const canonical = COURSE_CATALOG_DATA[c.slug];
            const existing = map.get(c.slug);
            map.set(c.slug, {
              ...existing,
              ...c,
              title: canonical?.title || c.title || existing?.title || "",
              description: canonical?.description || c.description || existing?.description || "",
              total_lessons: canonical?.total_lessons || existing?.total_lessons || 0,
            });
          }
        });
        return Array.from(map.values());
      }
    } catch (_) {}

    return defaultCatalog;
  },

  async getCourseDetails(courseSlug: string): Promise<CourseDetailResponse> {
    const canonical = COURSE_CATALOG_DATA[courseSlug];
    const canonicalTitle =
      canonical?.title ||
      courseSlug
        .split("-")
        .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
    const canonicalDescription =
      canonical?.description || `Comprehensive ${canonicalTitle} interview course.`;
    const canonicalTotal = canonical?.total_lessons || 10;

    try {
      const data = await this._fetchOptional(`/courses/${encodeURIComponent(courseSlug)}`);
      if (data && data.lessons && data.lessons.length > 2) {
        return {
          ...data,
          title: canonicalTitle,
          description: canonicalDescription,
          total_lessons: Math.max(data.total_lessons || 0, data.lessons.length, canonicalTotal),
        };
      }
    } catch (_) {}

    return {
      id: courseSlug,
      slug: courseSlug,
      title: canonicalTitle,
      description: canonicalDescription,
      total_lessons: canonicalTotal,
      completed_lessons: 0,
      progress_percentage: 0,
      lessons: Array.from({ length: canonicalTotal }, (_, i) => ({
        id: String(i + 1),
        slug: `step-${i + 1}`,
        title: `Chapter ${i + 1}`,
        order_index: i + 1,
        completed: false,
      })),
    };
  },

  async getLesson(courseSlug: string, lessonSlug: string): Promise<LessonDetailResponse> {
    try {
      const data = await this._fetchOptional(`/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}`);
      if (data && data.slug && data.content_markdown && data.content_markdown.length > 50) {
        return data;
      }
    } catch (_) {}

    // Parse step number
    const stepMatch = lessonSlug.match(/^step-(\d+)$/i) || lessonSlug.match(/^(\d+)$/);
    const stepNo = stepMatch ? parseInt(stepMatch[1], 10) : 1;



    return {
      id: String(stepNo),
      course_slug: courseSlug,
      slug: lessonSlug,
      title: `Chapter ${stepNo}`,
      order_index: stepNo,
      content_markdown: "# Lesson Content\n\nContent is being synced.",
      tasks: [],
      completed: false,
      prev_lesson_slug: stepNo > 1 ? `step-${stepNo - 1}` : null,
      next_lesson_slug: `step-${stepNo + 1}`,
    };
  },

  async completeLesson(courseSlug: string, lessonSlug: string): Promise<LessonCompleteResponse> {
    const stepMatch = lessonSlug.match(/^step-(\d+)$/i) || lessonSlug.match(/^(\d+)$/);
    const stepNo = stepMatch ? parseInt(stepMatch[1], 10) : 1;

    try {
      const data = await this._fetch(`/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}/complete`, {
        method: "POST",
      });
      if (data && data.success) {
        return data;
      }
    } catch (_) {}

    const res = await this.updateLearningTrackProgress(courseSlug, stepNo, true);
    const prog = await this.getLearningTrackProgress(courseSlug);

    return {
      success: true,
      course_slug: courseSlug,
      lesson_slug: lessonSlug,
      completed: true,
      completed_at: res?.updated_at || new Date().toISOString(),
      course_progress: {
        completed_lessons: prog?.completed_steps || 1,
        total_lessons: prog?.total_steps || 30,
        progress_percentage: prog?.completion_percent || 0,
      },
    };
  },

  async getCourseProgress(courseSlug: string): Promise<CourseProgressResponse> {
    try {
      const data = await this._fetchOptional(`/courses/${encodeURIComponent(courseSlug)}/progress`);
      if (data && typeof data.completed_lessons === "number") {
        return data;
      }
    } catch (_) {}

    let prog = null;
    try {
      prog = await this.getLearningTrackProgress(courseSlug);
    } catch (_) {
      prog = null;
    }
    const completedSlugs = (prog?.steps || [])
      .filter((s: any) => s.completed)
      .map((s: any) => `step-${s.step_no}`);

    return {
      course_slug: courseSlug,
      completed_lessons: prog?.completed_steps || 0,
      total_lessons: prog?.total_steps || 0,
      progress_percentage: prog?.completion_percent || 0,
      completed_lesson_slugs: completedSlugs,
    };
  },

  async getCourseSeedTables(courseSlug: string): Promise<SeedTablesResponse> {
    try {
      const data = await this._fetchOptional(`/courses/${encodeURIComponent(courseSlug)}/seed-tables`);
      if (data && data.tables) {
        return data;
      }
    } catch (_) {}

    return {
      course_slug: courseSlug,
      tables: [],
    };
  },
};

export interface CourseSummary {
  id: string;
  slug: string;
  title: string;
  description: string;
  total_lessons: number;
  completed_lessons?: number;
  progress_percentage?: number;
}

export interface CourseLessonSummary {
  id: string;
  slug: string;
  title: string;
  order_index: number;
  completed?: boolean;
}

export interface CourseDetailResponse {
  id: string;
  slug: string;
  title: string;
  description: string;
  total_lessons: number;
  completed_lessons?: number;
  progress_percentage?: number;
  lessons: CourseLessonSummary[];
}

export interface LessonDetailResponse {
  id: string;
  course_slug: string;
  slug: string;
  title: string;
  order_index: number;
  content_markdown: string;
  tasks: string[];
  completed?: boolean;
  prev_lesson_slug?: string | null;
  next_lesson_slug?: string | null;
}

export interface SeedTableDefinition {
  name: string;
  schema_sql: string;
  insert_sql: string;
  columns: string[];
  rows: any[][];
}

export interface SeedTablesResponse {
  course_slug: string;
  tables: SeedTableDefinition[];
}

export interface LessonCompleteResponse {
  success: boolean;
  course_slug: string;
  lesson_slug: string;
  completed: boolean;
  completed_at: string;
  course_progress: {
    completed_lessons: number;
    total_lessons: number;
    progress_percentage: number;
  };
}

export interface CourseProgressResponse {
  course_slug: string;
  completed_lessons: number;
  total_lessons: number;
  progress_percentage: number;
  completed_lesson_slugs: string[];
}



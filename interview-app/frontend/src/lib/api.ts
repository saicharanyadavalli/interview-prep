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

    try {
      const sb = getSupabase();
      if (sb && isNum) {
        const { data: { session } } = await sb.auth.getSession();
        if (session?.user) {
          const qnumVal = Number(questionRef);
          const updateData: Record<string, any> = {
            user_id: session.user.id,
            qnum: qnumVal,
            updated_at: new Date().toISOString(),
          };
          if (payload.is_solved !== undefined) updateData.is_solved = Boolean(payload.is_solved);
          if (payload.revisit !== undefined) updateData.is_revisit = Boolean(payload.revisit);

          await sb.from("user_progress").upsert(updateData, { onConflict: "user_id,qnum" });
        }
      }
    } catch (_) {}

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

    if (res && res.stats && (res.stats.total_attempted > 0 || res.stats.solved_count > 0)) {
      return res;
    }

    // Direct Supabase fallback
    try {
      const sb = getSupabase();
      if (sb) {
        const { data: { session } } = await sb.auth.getSession();
        if (session?.user) {
          const { data: entries } = await sb
            .from("user_progress")
            .select("*")
            .eq("user_id", session.user.id);

          if (entries && entries.length > 0) {
            const attempted = entries.length;
            const solved = entries.filter((e: any) => Boolean(e.is_solved)).length;
            const revisit = entries.filter((e: any) => Boolean(e.is_revisit)).length;
            return {
              stats: {
                total_attempted: attempted,
                solved_count: solved,
                unsolved_count: attempted - solved,
                revisit_count: revisit,
                easy_attempted: 0,
                medium_attempted: 0,
                hard_attempted: 0,
                easy_solved: 0,
                medium_solved: 0,
                hard_solved: 0,
                total_questions: 1081,
                solved_total_questions: solved,
                easy_total_questions: 448,
                medium_total_questions: 529,
                hard_total_questions: 104,
                easy_solved_total_questions: 0,
                medium_solved_total_questions: 0,
                hard_solved_total_questions: 0,
              },
              recent: entries.slice(0, 20).map((e: any) => ({
                qnum: e.qnum,
                question_id: `q_${e.qnum}`,
                question_title: `Question #${e.qnum}`,
                company: "",
                difficulty: "",
                is_solved: Boolean(e.is_solved),
                revisit: Boolean(e.is_revisit),
                updated_at: e.updated_at || "",
              })),
              topic_breakdown: [],
            };
          }
        }
      }
    } catch (_) {}

    return res || { stats: { total_attempted: 0, solved_count: 0, revisit_count: 0 }, recent: [] };
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
      if (cached && cached.username) {
        return cached;
      }
    }

    let profile: any = null;
    try {
      profile = await this._fetch("/profile/me");
    } catch (_) {}

    // Supabase client fallback to guarantee instant data retrieval
    try {
      const sb = getSupabase();
      if (sb) {
        const { data: { session } } = await sb.auth.getSession();
        if (session?.user) {
          const { data: dbRows } = await sb
            .from("user_profiles")
            .select("id,email,username,name,phone,avatar_url")
            .eq("id", session.user.id)
            .limit(1);

          if (dbRows && dbRows[0]) {
            const row = dbRows[0];
            profile = {
              id: row.id,
              email: row.email || session.user.email || "",
              username: row.username || profile?.username || session.user.user_metadata?.username || "",
              name: row.name || profile?.name || "",
              phone: row.phone || profile?.phone || "",
              avatar_url: row.avatar_url || profile?.avatar_url || "",
            };
          }
        }
      }
    } catch (_) {}

    if (profile) {
      this.setCachedProfile(profile);
    }
    return profile || { id: "", email: "", username: "", name: "", phone: "", avatar_url: "" };
  },

  async updateMyProfile(payload: any) {
    // Directly update Supabase user_profiles table as well for instant client consistency
    try {
      const sb = getSupabase();
      if (sb) {
        const { data: { session } } = await sb.auth.getSession();
        if (session?.user) {
          const upsertData: Record<string, any> = {
            id: session.user.id,
            email: session.user.email || "",
          };
          if (payload.name !== undefined) upsertData.name = String(payload.name).trim();
          if (payload.username !== undefined) upsertData.username = String(payload.username).trim().toLowerCase();
          if (payload.phone !== undefined) upsertData.phone = String(payload.phone).trim();
          if (payload.avatar_url !== undefined) upsertData.avatar_url = String(payload.avatar_url).trim();

          await sb.from("user_profiles").upsert(upsertData, { onConflict: "id" });
        }
      }
    } catch (_) {}

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

  // --- Courses API Endpoints ---
  async getCourses(): Promise<CourseSummary[]> {
    try {
      const data = await this._fetchOptional("/courses");
      if (Array.isArray(data) && data.length > 0) {
        return data;
      }
    } catch (_) {}

    // Fetch actual System Design learning tracks from /learning-tracks
    try {
      const res = await this.getLearningTracks();
      const tracks = res?.tracks || [];
      if (Array.isArray(tracks) && tracks.length > 0) {
        const results = await Promise.all(
          tracks.map(async (t: any) => {
            let completed = 0;
            let percent = 0;
            try {
              const p = await this.getLearningTrackProgress(t.track_id);
              if (p) {
                completed = p.completed_steps || 0;
                percent = p.completion_percent || 0;
              }
            } catch (_) {}

            return {
              id: t.track_id,
              slug: t.track_id,
              title: t.display_name,
              description: `Comprehensive ${t.display_name} interview learning track with ${t.step_count} step-by-step interactive chapters.`,
              total_lessons: t.step_count,
              completed_lessons: completed,
              progress_percentage: percent,
            };
          })
        );
        return results;
      }
    } catch (_) {}

    return [];
  },

  async getCourseDetails(courseSlug: string): Promise<CourseDetailResponse> {
    try {
      const data = await this._fetchOptional(`/courses/${encodeURIComponent(courseSlug)}`);
      if (data && data.lessons && data.lessons.length > 0) {
        return data;
      }
    } catch (_) {}

    // Fetch actual System Design learning track progress & steps
    let prog = null;
    try {
      prog = await this.getLearningTrackProgress(courseSlug);
    } catch (_) {
      prog = null;
    }
    const title = courseSlug
      .split("-")
      .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");

    return {
      id: courseSlug,
      slug: courseSlug,
      title,
      description: `Comprehensive ${title} interview course.`,
      total_lessons: prog?.total_steps || 0,
      completed_lessons: prog?.completed_steps || 0,
      progress_percentage: prog?.completion_percent || 0,
      lessons: (prog?.steps || []).map((s: any) => ({
        id: String(s.step_no),
        slug: `step-${s.step_no}`,
        title: s.title || `Chapter ${s.step_no}`,
        order_index: s.step_no,
        completed: Boolean(s.completed),
      })),
    };
  },

  async getLesson(courseSlug: string, lessonSlug: string): Promise<LessonDetailResponse> {
    try {
      const data = await this._fetchOptional(`/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}`);
      if (data && data.slug) {
        return data;
      }
    } catch (_) {}

    // Parse step number and fetch actual lesson content from /learning-tracks
    const stepMatch = lessonSlug.match(/^step-(\d+)$/i) || lessonSlug.match(/^(\d+)$/);
    const stepNo = stepMatch ? parseInt(stepMatch[1], 10) : 1;

    let data = null;
    let prog = null;
    try {
      data = await this.getLearningTrackLesson(courseSlug, stepNo);
    } catch (_) {
      data = null;
    }
    try {
      prog = await this.getLearningTrackProgress(courseSlug);
    } catch (_) {
      prog = null;
    }
    const currentStep = prog?.steps?.find((s: any) => s.step_no === stepNo);

    const prevLesson = stepNo > 1 ? `step-${stepNo - 1}` : null;
    const totalSteps = prog?.total_steps || 30;
    const nextLesson = stepNo < totalSteps ? `step-${stepNo + 1}` : null;

    return {
      id: String(stepNo),
      course_slug: courseSlug,
      slug: lessonSlug,
      title: data?.title || `Chapter ${stepNo}`,
      order_index: stepNo,
      content_markdown: data?.html_content || "",
      tasks: ["Review the chapter material", "Complete the self-assessment"],
      completed: Boolean(currentStep?.completed),
      prev_lesson_slug: prevLesson,
      next_lesson_slug: nextLesson,
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



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

  // --- Courses API Endpoints ---
  async getCourses(): Promise<CourseSummary[]> {
    try {
      const data = await this._fetch("/courses");
      if (Array.isArray(data) && data.length > 0) {
        return data;
      }
    } catch (err) {
      console.warn("Backend /courses endpoint unavailable, using fallback catalog:", err);
    }

    return [
      {
        id: "sql-course",
        slug: "sql-course",
        title: "SQL Practice Course",
        description: "Master SQL queries step-by-step with interactive sql.js practice tables and exercises.",
        total_lessons: FALLBACK_SQL_LESSONS.length,
        completed_lessons: getLocalProgress("sql-course").length,
        progress_percentage: Math.round((getLocalProgress("sql-course").length / FALLBACK_SQL_LESSONS.length) * 100),
      },
      {
        id: "system-design",
        slug: "system-design",
        title: "System Design Fundamentals",
        description: "Master large-scale distributed system design principles and interview patterns.",
        total_lessons: FALLBACK_SYSTEM_DESIGN_LESSONS.length,
        completed_lessons: getLocalProgress("system-design").length,
        progress_percentage: Math.round((getLocalProgress("system-design").length / FALLBACK_SYSTEM_DESIGN_LESSONS.length) * 100),
      },
      {
        id: "object-oriented-design",
        slug: "object-oriented-design",
        title: "Object-Oriented Design",
        description: "Learn OOD patterns, class diagrams, and SOLID design principles.",
        total_lessons: FALLBACK_OOD_LESSONS.length,
        completed_lessons: getLocalProgress("object-oriented-design").length,
        progress_percentage: Math.round((getLocalProgress("object-oriented-design").length / FALLBACK_OOD_LESSONS.length) * 100),
      },
    ];
  },

  async getCourseDetails(courseSlug: string): Promise<CourseDetailResponse> {
    try {
      const data = await this._fetch(`/courses/${encodeURIComponent(courseSlug)}`);
      if (data && data.lessons) {
        return data;
      }
    } catch (err) {
      console.warn(`Backend /courses/${courseSlug} unavailable, using fallback details:`, err);
    }

    const completedSlugs = getLocalProgress(courseSlug);
    let lessonsList: any[] = [];
    let title = "Interactive Course";
    let description = "Comprehensive interactive learning course.";

    if (courseSlug === "sql-course") {
      title = "SQL Practice Course";
      description = "Master SQL queries step-by-step with interactive sql.js practice tables and exercises.";
      lessonsList = FALLBACK_SQL_LESSONS;
    } else if (courseSlug === "system-design") {
      title = "System Design Fundamentals";
      description = "Master large-scale distributed system design principles and interview patterns.";
      lessonsList = FALLBACK_SYSTEM_DESIGN_LESSONS;
    } else if (courseSlug === "object-oriented-design") {
      title = "Object-Oriented Design";
      description = "Learn OOD patterns, class diagrams, and SOLID design principles.";
      lessonsList = FALLBACK_OOD_LESSONS;
    }

    const totalLessons = lessonsList.length;
    const completedCount = completedSlugs.length;
    const progressPct = totalLessons > 0 ? Math.round((completedCount / totalLessons) * 100) : 0;

    return {
      id: courseSlug,
      slug: courseSlug,
      title,
      description,
      total_lessons: totalLessons,
      completed_lessons: completedCount,
      progress_percentage: progressPct,
      lessons: lessonsList.map((l) => ({
        id: l.slug,
        slug: l.slug,
        title: l.title,
        order_index: l.order_index,
        completed: completedSlugs.includes(l.slug),
      })),
    };
  },

  async getLesson(courseSlug: string, lessonSlug: string): Promise<LessonDetailResponse> {
    try {
      const data = await this._fetch(`/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}`);
      if (data && data.slug) {
        return data;
      }
    } catch (err) {
      console.warn(`Backend /courses/${courseSlug}/lessons/${lessonSlug} unavailable, using fallback:`, err);
    }

    let lessonsList: any[] = [];
    if (courseSlug === "sql-course") lessonsList = FALLBACK_SQL_LESSONS;
    else if (courseSlug === "system-design") lessonsList = FALLBACK_SYSTEM_DESIGN_LESSONS;
    else if (courseSlug === "object-oriented-design") lessonsList = FALLBACK_OOD_LESSONS;

    const idx = lessonsList.findIndex((l) => l.slug === lessonSlug);
    const target = idx >= 0 ? lessonsList[idx] : lessonsList[0] || { slug: lessonSlug, title: lessonSlug, order_index: 1, content_markdown: "# Lesson Content", tasks: [] };
    const completedSlugs = getLocalProgress(courseSlug);

    const prevLesson = idx > 0 ? lessonsList[idx - 1].slug : null;
    const nextLesson = idx >= 0 && idx < lessonsList.length - 1 ? lessonsList[idx + 1].slug : null;

    return {
      id: target.slug,
      course_slug: courseSlug,
      slug: target.slug,
      title: target.title,
      order_index: target.order_index,
      content_markdown: target.content_markdown,
      tasks: target.tasks || [],
      completed: completedSlugs.includes(target.slug),
      prev_lesson_slug: prevLesson,
      next_lesson_slug: nextLesson,
    };
  },

  async completeLesson(courseSlug: string, lessonSlug: string): Promise<LessonCompleteResponse> {
    try {
      const data = await this._fetch(`/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}/complete`, {
        method: "POST",
      });
      if (data && data.success) {
        return data;
      }
    } catch (err) {
      console.warn(`Backend completeLesson unavailable, using local progress:`, err);
    }

    const updatedSlugs = setLocalProgress(courseSlug, lessonSlug, true);
    let lessonsList: any[] = [];
    if (courseSlug === "sql-course") lessonsList = FALLBACK_SQL_LESSONS;
    else if (courseSlug === "system-design") lessonsList = FALLBACK_SYSTEM_DESIGN_LESSONS;
    else if (courseSlug === "object-oriented-design") lessonsList = FALLBACK_OOD_LESSONS;

    const total = lessonsList.length || 1;
    const count = updatedSlugs.length;
    const pct = Math.round((count / total) * 100);

    return {
      success: true,
      course_slug: courseSlug,
      lesson_slug: lessonSlug,
      completed: true,
      completed_at: new Date().toISOString(),
      course_progress: {
        completed_lessons: count,
        total_lessons: total,
        progress_percentage: pct,
      },
    };
  },

  async getCourseProgress(courseSlug: string): Promise<CourseProgressResponse> {
    try {
      const data = await this._fetch(`/courses/${encodeURIComponent(courseSlug)}/progress`);
      if (data && typeof data.completed_lessons === "number") {
        return data;
      }
    } catch (err) {
      console.warn(`Backend getCourseProgress unavailable:`, err);
    }

    const completedSlugs = getLocalProgress(courseSlug);
    let lessonsList: any[] = [];
    if (courseSlug === "sql-course") lessonsList = FALLBACK_SQL_LESSONS;
    else if (courseSlug === "system-design") lessonsList = FALLBACK_SYSTEM_DESIGN_LESSONS;
    else if (courseSlug === "object-oriented-design") lessonsList = FALLBACK_OOD_LESSONS;

    const total = lessonsList.length || 1;
    const count = completedSlugs.length;
    const pct = Math.round((count / total) * 100);

    return {
      course_slug: courseSlug,
      completed_lessons: count,
      total_lessons: total,
      progress_percentage: pct,
      completed_lesson_slugs: completedSlugs,
    };
  },

  async getCourseSeedTables(courseSlug: string): Promise<SeedTablesResponse> {
    try {
      const data = await this._fetch(`/courses/${encodeURIComponent(courseSlug)}/seed-tables`);
      if (data && data.tables) {
        return data;
      }
    } catch (err) {
      console.warn(`Backend getCourseSeedTables unavailable, using fallback tables:`, err);
    }

    return {
      course_slug: courseSlug,
      tables: FALLBACK_SEED_TABLES,
    };
  },
};

// Helper functions and fallback data for offline / fallback courses support
function getLocalProgress(courseSlug: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(`ipp_course_progress_${courseSlug}`);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function setLocalProgress(courseSlug: string, lessonSlug: string, completed: boolean): string[] {
  if (typeof window === "undefined") return [];
  try {
    const current = new Set(getLocalProgress(courseSlug));
    if (completed) {
      current.add(lessonSlug);
    } else {
      current.delete(lessonSlug);
    }
    const arr = Array.from(current);
    localStorage.setItem(`ipp_course_progress_${courseSlug}`, JSON.stringify(arr));
    return arr;
  } catch {
    return [];
  }
}

const FALLBACK_SQL_LESSONS = [
  {
    slug: "select_queries_introduction",
    order_index: 1,
    title: "SQL Lesson 1: SELECT queries 101",
    content_markdown: `# SQL Lesson 1: SELECT queries 101\n\nTo retrieve data from a SQL database, write a \`SELECT\` statement. A query declares what data you want from the database.\n\nUse \`SELECT * FROM Movies;\` to view all columns of data from the \`Movies\` table.\n\n### Example Query\n\`\`\`sql\nSELECT Title, Director FROM Movies;\n\`\`\`\n\n# Exercise\nRun queries against the Pixar Movies database to solve each task.`,
    tasks: [
      "Find the title of each film",
      "Find the director of each film",
      "Find the title and director of each film",
      "Find all the information about each film",
    ],
  },
  {
    slug: "select_queries_with_constraints",
    order_index: 2,
    title: "SQL Lesson 2: Queries with constraints (Pt. 1)",
    content_markdown: `# SQL Lesson 2: Queries with constraints (Pt. 1)\n\nTo filter results from a table, use a \`WHERE\` clause in your query.\n\n| Operator | Condition | SQL Example |\n| --- | --- | --- |\n| =, !=, <, <=, >, >= | Numerical comparison | \`Length_minutes > 100\` |\n| BETWEEN ... AND ... | Within inclusive range | \`Year BETWEEN 2000 AND 2010\` |\n| IN (...) | Matches value in list | \`Director IN ('John Lasseter', 'Pete Docter')\` |\n\n### Example Query\n\`\`\`sql\nSELECT Title, Year FROM Movies WHERE Year >= 2000;\n\`\`\`\n\n# Exercise\nFilter the Movies table using numerical constraints to complete the tasks below.`,
    tasks: [
      "Find the movie with a row id of 6",
      "Find the movies released in the years between 2000 and 2010",
      "Find the movies not released in the years between 2000 and 2010",
      "Find the first 5 Pixar movies and their release year",
    ],
  },
  {
    slug: "select_queries_with_constraints_pt_2",
    order_index: 3,
    title: "SQL Lesson 3: Queries with constraints (Pt. 2)",
    content_markdown: `# SQL Lesson 3: Queries with constraints (Pt. 2)\n\nWhen filtering text columns, use string operators like \`LIKE\` and wildcards like \`%\`.\n\n| Operator | Condition | Example |\n| --- | --- | --- |\n| LIKE | Case-insensitive match | \`Title LIKE 'Toy Story%'\` |\n| NOT LIKE | Inverse string match | \`Title NOT LIKE 'Cars%'\` |\n\n### Example Query\n\`\`\`sql\nSELECT Title, Director FROM Movies WHERE Title LIKE 'Toy Story%';\n\`\`\`\n\n# Exercise\nFilter text data using string comparison operators.`,
    tasks: [
      "Find all the Toy Story movies",
      "Find all the movies directed by John Lasseter",
      "Find all the movies (and director) not directed by John Lasseter",
      "Find all the WALL-* movies",
    ],
  },
  {
    slug: "filtering_sorting_query_results",
    order_index: 4,
    title: "SQL Lesson 4: Filtering and sorting query results",
    content_markdown: `# SQL Lesson 4: Filtering and sorting query results\n\nUse \`DISTINCT\` to eliminate duplicate rows, and \`ORDER BY\` to sort results ascending (\`ASC\`) or descending (\`DESC\`).\n\n### Example Query\n\`\`\`sql\nSELECT DISTINCT Director FROM Movies ORDER BY Director ASC;\n\`\`\`\n\n# Exercise\nOrder and limit query results to answer the exercises below.`,
    tasks: [
      "List all directors of Pixar movies (alphabetically), without duplicates",
      "List the last four Pixar movies released (ordered from most recent to least)",
      "List the first five Pixar movies sorted alphabetically",
      "List the next five Pixar movies sorted alphabetically",
    ],
  },
];

const FALLBACK_SYSTEM_DESIGN_LESSONS = [
  {
    slug: "introduction-to-system-design",
    order_index: 1,
    title: "Lesson 1: Introduction to System Design",
    content_markdown: `# Introduction to System Design\n\nSystem design is the process of defining the architecture, interfaces, and data for a system to satisfy specified requirements.\n\n### Core Building Blocks\n1. **Client-Server Architecture**: Clients request resources from centralized servers.\n2. **DNS & Networking**: Domain Name System translates hostnames to IP addresses.\n3. **Stateless vs Stateful**: Stateless web servers allow horizontal scaling across server farms.\n\n### Key Metrics\n- **Latency**: Time taken to service a request (ms).\n- **Throughput**: Number of operations processed per second (QPS / RPS).\n- **Availability**: Percentage of uptime (e.g. 99.99% 'four nines').`,
    tasks: [
      "Understand client-server networking model",
      "Review high availability SLA calculations",
      "Differentiate latency versus throughput",
    ],
  },
  {
    slug: "load-balancing",
    order_index: 2,
    title: "Lesson 2: Load Balancing & Scaling",
    content_markdown: `# Load Balancing & Horizontal Scaling\n\nA Load Balancer (LB) distributes incoming network traffic across multiple backend servers to ensure high availability and reliability.\n\n### Load Balancing Algorithms\n- **Round Robin**: Requests distributed sequentially.\n- **Least Connections**: Route to server with fewest active connections.\n- **Consistent Hashing**: Hash keys map to ring topology for dynamic server additions.\n\n### Layer 4 vs Layer 7\n- **L4 Load Balancing**: Operates at Transport layer (TCP/UDP).\n- **L7 Load Balancing**: Operates at Application layer (HTTP/HTTPS headers, paths, cookies).`,
    tasks: [
      "Compare L4 vs L7 load balancing models",
      "Understand Consistent Hashing algorithm ring",
      "Design zero-downtime server scaling",
    ],
  },
];

const FALLBACK_OOD_LESSONS = [
  {
    slug: "solid-principles",
    order_index: 1,
    title: "Lesson 1: SOLID Design Principles",
    content_markdown: `# SOLID Principles in Object-Oriented Design\n\nThe SOLID principles are five design guidelines for building scalable, maintainable software.\n\n1. **S - Single Responsibility Principle (SRP)**: A class should have only one reason to change.\n2. **O - Open/Closed Principle (OCP)**: Software entities should be open for extension, closed for modification.\n3. **L - Liskov Substitution Principle (LSP)**: Derived classes must be substitutable for base classes.\n4. **I - Interface Segregation Principle (ISP)**: Clients should not be forced to depend on interfaces they do not use.\n5. **D - Dependency Inversion Principle (DIP)**: Depend upon abstractions, not concrete implementations.`,
    tasks: [
      "Apply Single Responsibility Principle to modular classes",
      "Implement Strategy Pattern following Open/Closed Principle",
      "Refactor code to conform to Dependency Inversion",
    ],
  },
];

const FALLBACK_SEED_TABLES: SeedTableDefinition[] = [
  {
    name: "Movies",
    schema_sql: "CREATE TABLE Movies (\n  Id INTEGER PRIMARY KEY,\n  Title TEXT NOT NULL,\n  Director TEXT NOT NULL,\n  Year INTEGER NOT NULL,\n  Length_minutes INTEGER NOT NULL\n);",
    insert_sql: "INSERT INTO Movies (Id, Title, Director, Year, Length_minutes) VALUES\n(1, 'Toy Story', 'John Lasseter', 1995, 81),\n(2, 'A Bug''s Life', 'John Lasseter', 1998, 95),\n(3, 'Toy Story 2', 'John Lasseter', 1999, 92),\n(4, 'Monsters, Inc.', 'Pete Docter', 2001, 92),\n(5, 'Finding Nemo', 'Andrew Stanton', 2003, 100),\n(6, 'The Incredibles', 'Brad Bird', 2004, 115),\n(7, 'Cars', 'John Lasseter', 2006, 117),\n(8, 'Ratatouille', 'Brad Bird', 2007, 111),\n(9, 'WALL-E', 'Andrew Stanton', 2008, 98),\n(10, 'Up', 'Pete Docter', 2009, 96),\n(11, 'Toy Story 3', 'Lee Unkrich', 2010, 103),\n(12, 'Cars 2', 'John Lasseter', 2011, 106),\n(13, 'Brave', 'Mark Andrews', 2012, 102),\n(14, 'Monsters University', 'Dan Scanlon', 2013, 104);",
    columns: ["Id", "Title", "Director", "Year", "Length_minutes"],
    rows: [
      [1, "Toy Story", "John Lasseter", 1995, 81],
      [2, "A Bug's Life", "John Lasseter", 1998, 95],
      [3, "Toy Story 2", "John Lasseter", 1999, 92],
      [4, "Monsters, Inc.", "Pete Docter", 2001, 92],
      [5, "Finding Nemo", "Andrew Stanton", 2003, 100],
      [6, "The Incredibles", "Brad Bird", 2004, 115],
      [7, "Cars", "John Lasseter", 2006, 117],
      [8, "Ratatouille", "Brad Bird", 2007, 111],
      [9, "WALL-E", "Andrew Stanton", 2008, 98],
      [10, "Up", "Pete Docter", 2009, 96],
      [11, "Toy Story 3", "Lee Unkrich", 2010, 103],
      [12, "Cars 2", "John Lasseter", 2011, 106],
      [13, "Brave", "Mark Andrews", 2012, 102],
      [14, "Monsters University", "Dan Scanlon", 2013, 104],
    ],
  },
  {
    name: "Boxoffice",
    schema_sql: "CREATE TABLE Boxoffice (\n  Movie_id INTEGER PRIMARY KEY REFERENCES Movies(Id),\n  Rating REAL NOT NULL,\n  Domestic_sales INTEGER NOT NULL,\n  International_sales INTEGER NOT NULL\n);",
    insert_sql: "INSERT INTO Boxoffice (Movie_id, Rating, Domestic_sales, International_sales) VALUES\n(5, 8.2, 380843261, 555900000),\n(14, 7.4, 268492764, 475066841),\n(8, 8.0, 206445654, 417282858),\n(12, 6.4, 191452396, 368400000),\n(3, 7.9, 245852179, 251600000),\n(6, 8.0, 261441092, 370001000),\n(9, 8.4, 223808164, 297500000),\n(11, 8.4, 415004880, 651964882),\n(1, 8.3, 191796233, 170162500),\n(7, 7.2, 244082982, 217900000),\n(10, 8.3, 293004164, 438338580),\n(4, 8.1, 289916256, 272900000),\n(2, 7.2, 162798565, 200600000),\n(13, 7.2, 237282182, 303165085);",
    columns: ["Movie_id", "Rating", "Domestic_sales", "International_sales"],
    rows: [
      [5, 8.2, 380843261, 555900000],
      [14, 7.4, 268492764, 475066841],
      [8, 8.0, 206445654, 417282858],
      [12, 6.4, 191452396, 368400000],
      [3, 7.9, 245852179, 251600000],
      [6, 8.0, 261441092, 370001000],
      [9, 8.4, 223808164, 297500000],
      [11, 8.4, 415004880, 651964882],
      [1, 8.3, 191796233, 170162500],
      [7, 7.2, 244082982, 217900000],
      [10, 8.3, 293004164, 438338580],
      [4, 8.1, 289916256, 272900000],
      [2, 7.2, 162798565, 200600000],
      [13, 7.2, 237282182, 303165085],
    ],
  },
  {
    name: "Buildings",
    schema_sql: "CREATE TABLE Buildings (\n  Building_name TEXT PRIMARY KEY,\n  Capacity INTEGER NOT NULL\n);",
    insert_sql: "INSERT INTO Buildings (Building_name, Capacity) VALUES\n('1e', 24),\n('1w', 32),\n('2e', 16),\n('2w', 20);",
    columns: ["Building_name", "Capacity"],
    rows: [
      ["1e", 24],
      ["1w", 32],
      ["2e", 16],
      ["2w", 20],
    ],
  },
  {
    name: "Employees",
    schema_sql: "CREATE TABLE Employees (\n  Role TEXT NOT NULL,\n  Name TEXT PRIMARY KEY,\n  Building TEXT,\n  Years_employed INTEGER NOT NULL\n);",
    insert_sql: "INSERT INTO Employees (Role, Name, Building, Years_employed) VALUES\n('Engineer', 'Becky A.', '1e', 4),\n('Engineer', 'Dan B.', '1e', 2),\n('Engineer', 'Sharon F.', '1e', 6),\n('Engineer', 'Dan M.', '1e', 4),\n('Engineer', 'Malik S.', '1e', 1),\n('Manager', 'Yair L.', '1e', 10),\n('Manager', 'Katrina M.', '2w', 6),\n('Manager', 'Shirley P.', '2w', 3),\n('Manager', 'Brian M.', '1e', 9),\n('Artist', 'Daniel V.', '1w', 4),\n('Artist', 'Brenda X.', '1w', 8),\n('Artist', 'Michael S.', '1w', 9),\n('Artist', 'Tanya E.', '1w', 2),\n('Artist', 'Sandra A.', '1w', 5);",
    columns: ["Role", "Name", "Building", "Years_employed"],
    rows: [
      ["Engineer", "Becky A.", "1e", 4],
      ["Engineer", "Dan B.", "1e", 2],
      ["Engineer", "Sharon F.", "1e", 6],
      ["Engineer", "Dan M.", "1e", 4],
      ["Engineer", "Malik S.", "1e", 1],
      ["Manager", "Yair L.", "1e", 10],
      ["Manager", "Katrina M.", "2w", 6],
      ["Manager", "Shirley P.", "2w", 3],
      ["Manager", "Brian M.", "1e", 9],
      ["Artist", "Daniel V.", "1w", 4],
      ["Artist", "Brenda X.", "1w", 8],
      ["Artist", "Michael S.", "1w", 9],
      ["Artist", "Tanya E.", "1w", 2],
      ["Artist", "Sandra A.", "1w", 5],
    ],
  },
  {
    name: "Cities",
    schema_sql: "CREATE TABLE Cities (\n  City TEXT PRIMARY KEY,\n  Country TEXT NOT NULL,\n  Population INTEGER NOT NULL,\n  Latitude REAL NOT NULL,\n  Longitude REAL NOT NULL\n);",
    insert_sql: "INSERT INTO Cities (City, Country, Population, Latitude, Longitude) VALUES\n('Guadalajara', 'Mexico', 1500800, 20.659698, -103.349609),\n('Toronto', 'Canada', 2795060, 43.653226, -79.383184),\n('Houston', 'United States', 2195914, 29.760427, -95.369803),\n('New York', 'United States', 8405837, 40.712775, -74.005973),\n('Philadelphia', 'United States', 1553165, 39.952584, -75.165222),\n('Havana', 'Cuba', 2106146, 23.05407, -82.345189),\n('Mexico City', 'Mexico', 8851080, 19.432608, -99.133208),\n('Phoenix', 'United States', 1513367, 33.448377, -112.074037),\n('Los Angeles', 'United States', 3884307, 34.052234, -118.243685),\n('Ecatepec de Morelos', 'Mexico', 1656107, 19.601841, -99.050674),\n('Montreal', 'Canada', 1717767, 45.501689, -73.567256),\n('Chicago', 'United States', 2718782, 41.878114, -87.629798);",
    columns: ["City", "Country", "Population", "Latitude", "Longitude"],
    rows: [
      ["Guadalajara", "Mexico", 1500800, 20.659698, -103.349609],
      [ "Toronto", "Canada", 2795060, 43.653226, -79.383184],
      ["Houston", "United States", 2195914, 29.760427, -95.369803],
      ["New York", "United States", 8405837, 40.712775, -74.005973],
      ["Philadelphia", "United States", 1553165, 39.952584, -75.165222],
      ["Havana", "Cuba", 2106146, 23.05407, -82.345189],
      ["Mexico City", "Mexico", 8851080, 19.432608, -99.133208],
      ["Phoenix", "United States", 1513367, 33.448377, -112.074037],
      ["Los Angeles", "United States", 3884307, 34.052234, -118.243685],
      ["Ecatepec de Morelos", "Mexico", 1656107, 19.601841, -99.050674],
      ["Montreal", "Canada", 1717767, 45.501689, -73.567256],
      ["Chicago", "United States", 2718782, 41.878114, -87.629798],
    ],
  },
];

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



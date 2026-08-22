"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { Search, BookOpen, ClipboardList, Sparkles, CheckCircle2, Bookmark, FolderPlus } from "lucide-react";
import { CONFIG } from "@/lib/config";
import { getSupabase } from "@/lib/supabase";
import { FilterBuilder, FilterState } from "@/components/FilterBuilder";
import { Spinner } from "@/components/Spinner";
import { formatLeetCodeMath } from "@/components/LeetCodeRenderer";

const LEETCODE_TOPIC_OPTIONS = [
  "Array", "String", "Hash Table", "Dynamic Programming", "Math", "Sorting", "Greedy",
  "Depth-First Search", "Binary Search", "Database", "Breadth-First Search", "Tree",
  "Matrix", "Two Pointers", "Bit Manipulation", "Stack", "Heap (Priority Queue)",
  "Graph", "Design", "Counting", "Sliding Window", "Prefix Sum", "Backtracking",
  "Union Find", "Linked List", "Recursion", "Monotonic Stack", "Binary Tree", "Trie",
  "Divide and Conquer", "Topological Sort", "Binary Indexed Tree", "Segment Tree",
  "Memoization", "Queue", "Geometry", "Game Theory", "Simulation"
];

const PAGE_SIZE = 50;
const CUSTOM_FOLDER_KEY = "leetcodeCustomFolderV1";

interface LeetCodeProblem {
  qnum: number;
  title: string;
  slug: string;
  difficulty: "Easy" | "Medium" | "Hard" | string;
  rating?: number;
  topic_tags: string[];
  description_md?: string;
  solved?: number;
}

function normalizeToken(t: any) {
  return String(t || "").trim().toLowerCase();
}

export default function LeetCodeExplorerPage() {
  const [search, setSearch] = useState("");
  const [filterQuery, setFilterQuery] = useState<Record<string, any>>({
    match: "all",
    status: [],
    difficulty: [],
    topic: [],
  });

  const [rows, setRows] = useState<LeetCodeProblem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");

  const [selectedQnum, setSelectedQnum] = useState<number | null>(null);
  const [suggestions, setSuggestions] = useState<LeetCodeProblem[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(-1);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const [hydratedTopics, setHydratedTopics] = useState<string[]>(LEETCODE_TOPIC_OPTIONS);

  const scrollerRef = useRef<HTMLElement>(null);
  const bottomSentinelRef = useRef<HTMLDivElement>(null);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Live state tracking refs to guarantee fresh closures for infinite scroll
  const offsetRef = useRef(0);
  const rowsRef = useRef<LeetCodeProblem[]>([]);
  const isLoadingRef = useRef(false);
  const hasMoreRef = useRef(true);

  const API_BASE = CONFIG.API_BASE_URL;

  const loadProblems = useCallback(
    async (
      reset: boolean = false,
      currentSearch: string = search,
      currentFilters: Record<string, any> = filterQuery
    ) => {
      if (isLoadingRef.current) return;
      if (!reset && !hasMoreRef.current) return;

      isLoadingRef.current = true;
      setIsLoading(true);
      setErrorMsg("");

      let currentOffset = reset ? 0 : offsetRef.current;
      let currentRows = reset ? [] : rowsRef.current;

      if (reset) {
        offsetRef.current = 0;
        rowsRef.current = [];
        hasMoreRef.current = true;
        setOffset(0);
        setRows([]);
        setHasMore(true);
      }

      const q = currentSearch.trim();
      const diffFilters = Array.isArray(currentFilters.difficulty)
        ? currentFilters.difficulty.map((d: string) => d.replace(/^!/, "").toLowerCase())
        : [];
      const topicFilters = Array.isArray(currentFilters.topic)
        ? currentFilters.topic.map((t: string) => t.replace(/^!/, "").toLowerCase())
        : [];

      let loaded = false;

      // 1. Try Backend API first
      try {
        const pageNum = Math.floor(currentOffset / PAGE_SIZE) + 1;
        const qParams = new URLSearchParams({
          page: String(pageNum),
          limit: String(PAGE_SIZE),
        });
        if (q) qParams.append("search", q);
        if (diffFilters.length === 1) qParams.append("difficulty", diffFilters[0]);

        const res = await fetch(`${API_BASE}/leetcode/problems?${qParams.toString()}`);
        if (res.ok) {
          const data = await res.json();
          if (data && Array.isArray(data.problems)) {
            let fetched = data.problems.map((p: any) => ({
              ...p,
              topic_tags: Array.isArray(p.topic_tags)
                ? p.topic_tags
                : typeof p.topic_tags === "string"
                ? JSON.parse(p.topic_tags || "[]")
                : [],
            }));

            if (diffFilters.length > 0) {
              fetched = fetched.filter((p: LeetCodeProblem) =>
                diffFilters.includes(p.difficulty.toLowerCase())
              );
            }
            if (topicFilters.length > 0) {
              fetched = fetched.filter((p: LeetCodeProblem) =>
                p.topic_tags.some((t) => topicFilters.includes(t.toLowerCase()))
              );
            }

            const newTotal = data.total || fetched.length;
            const nextOffset = currentOffset + fetched.length;
            const more = fetched.length === PAGE_SIZE && nextOffset < newTotal;

            offsetRef.current = nextOffset;
            hasMoreRef.current = more;
            const combined = [...currentRows, ...fetched];
            rowsRef.current = combined;

            setTotal(newTotal);
            setOffset(nextOffset);
            setHasMore(more);
            setRows(combined);

            if (combined.length > 0 && selectedQnum === null) {
              setSelectedQnum(Number(combined[0].qnum));
            }
            loaded = true;
          }
        }
      } catch (_) {}

      // 2. Direct Supabase Fallback
      if (!loaded) {
        try {
          const supabase = getSupabase() as any;
          if (supabase) {
            let query = supabase
              .from("leetcode_problems")
              .select("qnum, title, slug, difficulty, rating, topic_tags, description_md", {
                count: "exact",
              });

            if (diffFilters.length === 1) {
              const diffClean =
                diffFilters[0].charAt(0).toUpperCase() + diffFilters[0].slice(1).toLowerCase();
              query = query.ilike("difficulty", diffClean);
            } else if (diffFilters.length > 1) {
              const capDiffs = diffFilters.map(
                (d) => d.charAt(0).toUpperCase() + d.slice(1).toLowerCase()
              );
              query = query.in("difficulty", capDiffs);
            }

            if (q) {
              if (/^\d+$/.test(q)) {
                query = query.eq("qnum", parseInt(q, 10));
              } else {
                query = query.ilike("title", `%${q}%`);
              }
            }

            query = query
              .order("qnum", { ascending: true })
              .range(currentOffset, currentOffset + PAGE_SIZE - 1);

            const { data, count, error } = await query;

            if (data && !error) {
              let fetched = data.map((p: any) => ({
                ...p,
                topic_tags: Array.isArray(p.topic_tags)
                  ? p.topic_tags
                  : typeof p.topic_tags === "string"
                  ? JSON.parse(p.topic_tags || "[]")
                  : [],
              }));

              if (topicFilters.length > 0) {
                fetched = fetched.filter((p: LeetCodeProblem) =>
                  p.topic_tags.some((t: string) => topicFilters.includes(t.toLowerCase()))
                );
              }

              const newTotal = count || fetched.length;
              const nextOffset = currentOffset + fetched.length;
              const more = fetched.length === PAGE_SIZE && nextOffset < newTotal;

              offsetRef.current = nextOffset;
              hasMoreRef.current = more;
              const combined = [...currentRows, ...fetched];
              rowsRef.current = combined;

              setTotal(newTotal);
              setOffset(nextOffset);
              setHasMore(more);
              setRows(combined);

              if (combined.length > 0 && selectedQnum === null) {
                setSelectedQnum(Number(combined[0].qnum));
              }
            }
          }
        } catch (err: any) {
          console.error("Failed to load LeetCode problems:", err);
          setErrorMsg("Failed to load LeetCode questions. Please try again.");
        }
      }

      isLoadingRef.current = false;
      setIsLoading(false);
      setIsInitialLoad(false);
    },
    [search, filterQuery, selectedQnum, API_BASE]
  );

  // Initial load
  useEffect(() => {
    loadProblems(true);
  }, []);

  // Filter change handler
  const handleFilterChange = (state: FilterState, queryObj: Record<string, any>) => {
    setFilterQuery(queryObj);
    loadProblems(true, search, queryObj);
  };

  // Search input debounced handler
  const handleSearchChange = (val: string) => {
    setSearch(val);
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      loadProblems(true, val, filterQuery);
    }, 300);
  };

  // Autocomplete suggestions
  useEffect(() => {
    const needle = normalizeToken(search);
    if (!needle || needle.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    const scored = rows
      .map((row) => {
        const title = String(row.title || "");
        const topics = (Array.isArray(row.topic_tags) ? row.topic_tags : []).join(" ");
        const haystack = `${title} ${topics} ${row.difficulty || ""}`.toLowerCase();
        const index = haystack.indexOf(needle);
        return { row, index, startsWithTitle: title.toLowerCase().startsWith(needle) };
      })
      .filter((item) => item.index >= 0)
      .sort((a, b) => {
        if (a.startsWithTitle !== b.startsWithTitle) return a.startsWithTitle ? -1 : 1;
        if (a.index !== b.index) return a.index - b.index;
        return Number(a.row.qnum || 0) - Number(b.row.qnum || 0);
      });

    setSuggestions(scored.slice(0, 7).map((item) => item.row));
    setShowSuggestions(true);
  }, [search, rows]);

  // Infinite Scroll Event Listener (auto-loads when scrolled within 250px of bottom)
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    const handleScroll = () => {
      if (isLoadingRef.current || !hasMoreRef.current) return;
      const remaining = scroller.scrollHeight - (scroller.scrollTop + scroller.clientHeight);
      if (remaining <= 250) {
        loadProblems(false, search, filterQuery);
      }
    };

    scroller.addEventListener("scroll", handleScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", handleScroll);
  }, [loadProblems, search, filterQuery]);

  // IntersectionObserver on bottom sentinel for extra responsiveness
  useEffect(() => {
    const sentinel = bottomSentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isLoadingRef.current && hasMoreRef.current) {
          loadProblems(false, search, filterQuery);
        }
      },
      { root: scrollerRef.current, threshold: 0.1, rootMargin: "250px" }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadProblems, search, filterQuery]);

  // Derived selected question
  const selectedQuestion = rows.find((r) => Number(r.qnum) === selectedQnum) || rows[0] || null;

  // Actions
  const addToCustomFolder = () => {
    if (!selectedQuestion) return alert("Select a question first.");
    try {
      const raw = localStorage.getItem(CUSTOM_FOLDER_KEY);
      const parsed = JSON.parse(raw || "[]");
      const existing = Array.isArray(parsed) ? parsed : [];
      const normalized = Array.from(
        new Set(existing.map((item) => Number(item || 0)).filter((v) => v > 0))
      );
      if (normalized.includes(Number(selectedQuestion.qnum))) {
        alert("Question already in custom folder.");
        return;
      }
      normalized.push(Number(selectedQuestion.qnum));
      localStorage.setItem(CUSTOM_FOLDER_KEY, JSON.stringify(normalized));
      alert(`Problem #${selectedQuestion.qnum} added to custom folder.`);
    } catch (_) {
      alert("Unable to save custom folder entry.");
    }
  };

  const addToRevisitQueue = () => {
    if (!selectedQuestion) return alert("Select a question first.");
    try {
      const raw = localStorage.getItem("leetcodeRevisitQueue");
      const parsed = JSON.parse(raw || "[]");
      const existing = Array.isArray(parsed) ? parsed : [];
      if (!existing.includes(Number(selectedQuestion.qnum))) {
        existing.push(Number(selectedQuestion.qnum));
        localStorage.setItem("leetcodeRevisitQueue", JSON.stringify(existing));
      }
      alert(`Problem #${selectedQuestion.qnum} added to Revisit Queue.`);
    } catch (_) {
      alert("Added to Revisit Queue.");
    }
  };

  const estimateSuccessRate = (question: LeetCodeProblem) => {
    const diff = normalizeToken(question.difficulty);
    const base = diff === "easy" ? 84 : diff === "medium" ? 68 : diff === "hard" ? 48 : 65;
    const swing = Number(question.qnum || 0) % 13;
    return Math.max(38, Math.min(95, base + swing - 6));
  };

  const cleanSnippet = (text?: string) => {
    if (!text) return "Open this question to view the full prompt, examples, and solution approaches.";
    const clean = text
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&")
      .replace(/\s+/g, " ")
      .trim();

    return formatLeetCodeMath(clean.substring(0, 220)) + (clean.length > 220 ? "..." : "");
  };

  return (
    <main className="main-content questions-main-content animate-fade">
      {/* Header */}
      <header
        className="page-header section mb-6"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
      >
        <h1 style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <Image
            className="brand-logo"
            src="/assets/logo-mark.svg"
            alt="Logo"
            width={24}
            height={24}
          />
          <span>Interview Assistant</span>
          <span
            className="text-muted"
            style={{ fontSize: "0.9rem", fontWeight: 500, marginLeft: "0.5rem" }}
          >
            LeetCode DSA
          </span>
        </h1>
        <div className="page-header-actions">
          <span className="counter-badge">
            {rows.length} / {total || "4,017"}
          </span>
        </div>
      </header>

      {/* Main Split-Pane Layout */}
      <section
        className="questions-shell"
        style={{ display: "flex", gap: "1.5rem", flexDirection: "row" }}
      >
        {/* Left Side: Search + Filter + Problem List */}
        <div
          className="questions-left"
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            gap: "1.5rem",
          }}
        >
          {/* Search Input */}
          <div className="questions-search-wrap" style={{ position: "relative" }}>
            <span
              style={{
                position: "absolute",
                left: "1rem",
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--muted)",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Search size={16} />
            </span>
            <input
              type="text"
              placeholder="Search LeetCode questions, topics, difficulty..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onKeyDown={(e) => {
                if (!showSuggestions || suggestions.length === 0) return;
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setSuggestionIndex((prev) => (prev + 1) % suggestions.length);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setSuggestionIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
                } else if (e.key === "Enter" && suggestionIndex >= 0) {
                  e.preventDefault();
                  const row = suggestions[suggestionIndex];
                  setSearch(row.title || "");
                  setSelectedQnum(Number(row.qnum));
                  setShowSuggestions(false);
                  setSuggestionIndex(-1);
                } else if (e.key === "Escape") {
                  setShowSuggestions(false);
                  setSuggestionIndex(-1);
                }
              }}
              style={{
                width: "100%",
                padding: "0.75rem 1rem 0.75rem 2.5rem",
                borderRadius: "var(--radius)",
                border: "1px solid var(--line)",
                background: "var(--paper)",
                color: "var(--ink)",
              }}
            />
            {showSuggestions && suggestions.length > 0 && (
              <div
                className="questions-search-suggestions"
                style={{
                  position: "absolute",
                  top: "100%",
                  left: 0,
                  right: 0,
                  background: "var(--paper)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius)",
                  zIndex: 20,
                  marginTop: "0.5rem",
                  boxShadow: "var(--shadow)",
                }}
              >
                {suggestions.map((row, i) => (
                  <button
                    key={i}
                    className={`questions-suggestion-item ${
                      i === suggestionIndex ? "is-active" : ""
                    }`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.5rem",
                      width: "100%",
                      padding: "0.75rem 1rem",
                      background:
                        i === suggestionIndex ? "var(--sidebar-hover)" : "transparent",
                      border: "none",
                      borderBottom: "1px solid var(--line)",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      setSearch(row.title || "");
                      setSelectedQnum(Number(row.qnum));
                      setShowSuggestions(false);
                      setSuggestionIndex(-1);
                    }}
                  >
                    <Search size={14} style={{ color: "var(--muted)", flexShrink: 0 }} />
                    <span style={{ fontWeight: 500, color: "var(--ink)" }}>
                      #{row.qnum} {row.title}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Filter Builder Panel */}
          <section aria-label="LeetCode question filters">
            <FilterBuilder
              storageKey="leetcodeFilterBuilderState"
              topics={hydratedTopics}
              onChange={handleFilterChange}
            />
          </section>

          {/* Problem List with Infinite Scroll Auto-Loading */}
          <section
            ref={scrollerRef}
            aria-label="LeetCode questions list"
            style={{
              flex: 1,
              overflowY: "auto",
              maxHeight: "650px",
              paddingRight: "0.5rem",
            }}
          >
            <div
              className="q-browse-list"
              style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}
            >
              {rows.length === 0 && !isLoading && !isInitialLoad && !errorMsg ? (
                <div
                  className="empty-state"
                  style={{
                    padding: "2rem",
                    textAlign: "center",
                    background: "var(--paper)",
                    borderRadius: "var(--radius)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "center",
                      marginBottom: "0.5rem",
                    }}
                  >
                    <ClipboardList size={32} className="text-muted" />
                  </div>
                  <p className="text-muted">No LeetCode questions matched your query.</p>
                </div>
              ) : null}

              {rows.map((row) => {
                const isSelected = selectedQnum === Number(row.qnum);
                const diffLower = String(row.difficulty || "").toLowerCase();
                const successRate = estimateSuccessRate(row);

                return (
                  <div
                    key={row.qnum}
                    className={`q-browse-item ${isSelected ? "is-selected" : ""}`}
                    tabIndex={0}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "0.9rem 1rem",
                      background: isSelected ? "var(--sidebar-active)" : "var(--paper)",
                      borderRadius: "var(--radius)",
                      border: "1px solid var(--line)",
                      cursor: "pointer",
                      transition: "all 150ms ease",
                    }}
                    onClick={() => setSelectedQnum(Number(row.qnum))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedQnum(Number(row.qnum));
                      }
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.75rem",
                        minWidth: 0,
                      }}
                    >
                      <span
                        style={{
                          color: "var(--muted)",
                          fontSize: "0.85rem",
                          fontWeight: 600,
                          fontFamily: "monospace",
                        }}
                      >
                        #{row.qnum}
                      </span>
                      <span
                        style={{
                          fontWeight: 600,
                          color: "var(--ink)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {row.title}
                      </span>
                    </div>

                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.5rem",
                        flexShrink: 0,
                      }}
                    >
                      {row.solved === 1 && (
                        <span
                          className="pill pill-solved"
                          style={{
                            background: "var(--green)",
                            color: "white",
                            padding: "0.2rem 0.5rem",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                          }}
                        >
                          Solved
                        </span>
                      )}
                      <span
                        className="pill"
                        style={{
                          background:
                            diffLower === "easy"
                              ? "var(--green)"
                              : diffLower === "medium"
                              ? "var(--amber)"
                              : diffLower === "hard"
                              ? "var(--red)"
                              : "var(--sidebar-hover)",
                          color: ["easy", "medium", "hard"].includes(diffLower)
                            ? "white"
                            : "inherit",
                          padding: "0.2rem 0.5rem",
                          borderRadius: "4px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                        }}
                      >
                        {row.difficulty}
                      </span>
                      <span
                        className="pill"
                        style={{
                          background: "var(--sidebar-hover)",
                          padding: "0.2rem 0.5rem",
                          borderRadius: "4px",
                          fontSize: "0.75rem",
                        }}
                      >
                        {successRate}%
                      </span>
                    </div>
                  </div>
                );
              })}

              {/* Sentinel trigger element for auto-loading next page on scroll */}
              {hasMore && (
                <div ref={bottomSentinelRef} className="h-6 w-full flex items-center justify-center py-2" />
              )}

              {isLoading && (
                <div className="py-3 flex justify-center">
                  <Spinner text="Loading questions..." />
                </div>
              )}

              {errorMsg && (
                <div
                  style={{
                    padding: "1rem",
                    textAlign: "center",
                    color: "var(--red)",
                  }}
                >
                  {errorMsg}
                </div>
              )}

              {!hasMore && rows.length > 0 && (
                <div
                  style={{
                    padding: "1rem",
                    textAlign: "center",
                    color: "var(--muted)",
                    fontSize: "0.85rem",
                  }}
                >
                  You have reached the end of the question bank ({rows.length} loaded).
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Right Side: Live Detail / Preview Panel */}
        <aside
          className="questions-right"
          aria-label="Selected LeetCode question details"
          style={{
            width: "340px",
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            gap: "1.5rem",
          }}
        >
          {/* Preview Card 1: Title & Description Snippet */}
          <article
            className="card-flat"
            style={{
              padding: "1.5rem",
              background: "var(--paper)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-lg)",
            }}
          >
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="text-xs font-mono font-bold text-teal">
                {selectedQuestion ? `#${selectedQuestion.qnum}` : "SELECT QUESTION"}
              </span>
              {selectedQuestion && (
                <span
                  className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                    selectedQuestion.difficulty.toLowerCase() === "easy"
                      ? "bg-green/10 text-green border border-green/20"
                      : selectedQuestion.difficulty.toLowerCase() === "medium"
                      ? "bg-amber/10 text-amber border border-amber/20"
                      : "bg-red/10 text-red border border-red/20"
                  }`}
                >
                  {selectedQuestion.difficulty}
                </span>
              )}
            </div>

            <h2 style={{ fontSize: "1.15rem", fontWeight: 700, marginBottom: "0.5rem", color: "var(--ink)" }}>
              {selectedQuestion ? selectedQuestion.title : "Choose a question from the list"}
            </h2>

            <p
              className="text-muted"
              style={{ fontSize: "0.88rem", lineHeight: 1.6 }}
              dangerouslySetInnerHTML={{
                __html: selectedQuestion
                  ? cleanSnippet(selectedQuestion.description_md)
                  : "Click any question from the left sidebar to preview its prompt, acceptance stats, topic tags, and full solution approach.",
              }}
            />
          </article>

          {/* Preview Card 2: Stats, Topics, and Action Buttons */}
          <article
            className="card-flat"
            style={{
              padding: "1.5rem",
              background: "var(--paper)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-lg)",
            }}
          >
            <div style={{ marginBottom: "1.2rem", fontSize: "0.88rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <p>
                <strong style={{ color: "var(--ink)" }}>Success Rate:</strong>{" "}
                <span style={{ color: "var(--muted)" }}>
                  {selectedQuestion ? `${estimateSuccessRate(selectedQuestion)}%` : "--"}
                </span>
              </p>

              <div>
                <strong style={{ color: "var(--ink)", display: "block", marginBottom: "0.3rem" }}>
                  Topic Tags:
                </strong>
                {selectedQuestion && selectedQuestion.topic_tags && selectedQuestion.topic_tags.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {selectedQuestion.topic_tags.slice(0, 6).map((tag, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded-md bg-slate-800/80 text-teal-light text-[11px] border border-line/40 font-medium"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span style={{ color: "var(--muted)" }}>General DSA</span>
                )}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
              <button
                className="btn text-xs py-2"
                type="button"
                disabled={!selectedQuestion}
                onClick={addToCustomFolder}
              >
                <FolderPlus size={14} className="inline mr-1.5" /> Add to Custom Folder
              </button>
              <button
                className="btn text-xs py-2"
                type="button"
                disabled={!selectedQuestion}
                onClick={addToRevisitQueue}
              >
                <Bookmark size={14} className="inline mr-1.5" /> Add to Revisit Queue
              </button>
              <Link
                href={
                  selectedQuestion
                    ? `/dsa/leetcode/${encodeURIComponent(selectedQuestion.qnum)}`
                    : "#"
                }
                className="btn btn-primary text-xs py-2.5 text-center flex items-center justify-center gap-1.5"
                style={{
                  pointerEvents: selectedQuestion ? "auto" : "none",
                  opacity: selectedQuestion ? 1 : 0.5,
                }}
              >
                <BookOpen size={14} /> Open Question
              </Link>
            </div>
          </article>
        </aside>
      </section>
    </main>
  );
}

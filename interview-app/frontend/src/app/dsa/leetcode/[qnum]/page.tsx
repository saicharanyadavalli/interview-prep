"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Code2,
  Lightbulb,
  Copy,
  Check,
  Clock,
  Cpu,
  BookOpen,
  FolderPlus,
  Bookmark,
  Share2,
} from "lucide-react";
import { CONFIG } from "@/lib/config";
import { getSupabase } from "@/lib/supabase";
import { LeetCodeRenderer, formatLeetCodeMath } from "@/components/LeetCodeRenderer";
import { Spinner } from "@/components/Spinner";

interface ProblemDetail {
  qnum: number;
  title: string;
  slug: string;
  difficulty: string;
  rating?: number;
  topic_tags: string[];
  description_md: string;
}

interface Approach {
  approach_index: number;
  title: string;
  intuition_md: string;
  time_complexity: string;
  space_complexity: string;
  explanation_md: string;
}

interface CodeData {
  qnum: number;
  languages: string[];
  solutions: Record<string, string>;
}

export default function LeetCodeProblemPage() {
  const params = useParams();
  const qnum = params?.qnum ? parseInt(params.qnum as string, 10) : null;

  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [approaches, setApproaches] = useState<Approach[]>([]);
  const [codeData, setCodeData] = useState<CodeData | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("python");
  const [copied, setCopied] = useState<boolean>(false);
  const [showSolutionDropdown, setShowSolutionDropdown] = useState<boolean>(true);
  const [showCodeDropdown, setShowCodeDropdown] = useState<boolean>(true);

  const API_BASE = CONFIG.API_BASE_URL;

  useEffect(() => {
    if (!qnum) return;
    fetchProblemDetail();
  }, [qnum]);

  const fetchProblemDetail = async () => {
    setLoading(true);
    const supabase = getSupabase();

    try {
      // 1. Description
      let loadedProb = false;
      try {
        const resProb = await fetch(`${API_BASE}/leetcode/problems/${qnum}`);
        if (resProb.ok) {
          const pData = await resProb.json();
          if (pData && pData.title) {
            setProblem(pData);
            loadedProb = true;
          }
        }
      } catch (_) {}

      if (!loadedProb && supabase) {
        const { data: pData } = await (supabase as any)
          .from("leetcode_problems")
          .select("*")
          .eq("qnum", qnum)
          .maybeSingle();

        if (pData) {
          setProblem({
            ...pData,
            topic_tags: Array.isArray(pData.topic_tags)
              ? pData.topic_tags
              : typeof pData.topic_tags === "string"
              ? JSON.parse(pData.topic_tags || "[]")
              : [],
          });
        }
      }

      // 2. Fetch Approaches
      let loadedApp = false;
      try {
        const resApp = await fetch(`${API_BASE}/leetcode/problems/${qnum}/approaches`);
        if (resApp.ok) {
          const aData = await resApp.json();
          if (Array.isArray(aData) && aData.length > 0) {
            setApproaches(aData);
            loadedApp = true;
          }
        }
      } catch (_) {}

      if (!loadedApp && supabase) {
        const { data: aData } = await (supabase as any)
          .from("leetcode_approaches")
          .select("*")
          .eq("qnum", qnum)
          .order("approach_index", { ascending: true });

        if (aData && aData.length > 0) {
          setApproaches(aData);
        }
      }

      // 3. Fetch Code snippets
      let loadedCode = false;
      try {
        const resCode = await fetch(`${API_BASE}/leetcode/problems/${qnum}/code`);
        if (resCode.ok) {
          const cData = await resCode.json();
          if (cData && cData.languages && cData.languages.length > 0) {
            setCodeData(cData);
            const pref = cData.languages.includes("python") ? "python" : cData.languages[0];
            setSelectedLanguage(pref);
            loadedCode = true;
          }
        }
      } catch (_) {}

      if (!loadedCode && supabase) {
        const { data: cRows } = await (supabase as any)
          .from("leetcode_code_solutions")
          .select("language, code_content")
          .eq("qnum", qnum)
          .order("language", { ascending: true });

        if (cRows && cRows.length > 0) {
          const solutions: Record<string, string> = {};
          cRows.forEach((r: any) => {
            solutions[r.language] = r.code_content;
          });
          const languages = Object.keys(solutions);
          setCodeData({ qnum: Number(qnum), languages, solutions });
          setSelectedLanguage(languages.includes("python") ? "python" : languages[0]);
        }
      }
    } catch (err) {
      console.error("Error fetching problem data:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getDifficultyBadge = (diff?: string) => {
    switch (diff?.toLowerCase()) {
      case "easy":
        return "bg-green/10 text-green border-green/20";
      case "medium":
        return "bg-amber/10 text-amber border-amber/20";
      case "hard":
        return "bg-red/10 text-red border-red/20";
      default:
        return "bg-slate-500/10 text-slate-400 border-slate-500/20";
    }
  };

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center min-h-[60vh]">
        <Spinner text={`Loading Problem #${qnum}...`} />
      </main>
    );
  }

  if (!problem) {
    return (
      <main className="main-content flex flex-col items-center justify-center min-h-[60vh]">
        <div className="card-flat p-8 max-w-md text-center">
          <h2 className="text-xl font-bold text-red-400 mb-2">Problem Not Found</h2>
          <p className="text-gray-400 mb-6">Could not find LeetCode problem #{qnum}.</p>
          <Link href="/dsa/leetcode" className="btn btn-primary inline-flex items-center gap-2">
            <ArrowLeft size={16} /> Back to LeetCode DSA
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="main-content animate-fade space-y-6 pb-12">
      {/* Top Breadcrumb Navigation */}
      <div className="flex items-center justify-between">
        <Link
          href="/dsa/leetcode"
          className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-slate-900/80 border border-line/60 text-xs font-semibold text-gray-300 hover:text-teal hover:border-teal/40 hover:bg-teal/5 transition-all shadow-sm group"
          aria-label="Back to LeetCode DSA"
        >
          <ArrowLeft size={14} className="text-gray-400 group-hover:text-teal transition-colors" />
          <span>Back to LeetCode DSA</span>
        </Link>
      </div>

      {/* Problem Header Card */}
      <div className="card-flat p-6 md:p-8 rounded-2xl bg-paper/90 border border-line/60 backdrop-blur-md shadow-md space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-mono font-bold text-teal mb-1.5">
              <span>LEETCODE QUESTION #{problem.qnum}</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-bold text-white tracking-tight">
              {problem.title}
            </h1>
          </div>

          <span
            className={`self-start sm:self-auto px-3.5 py-1 rounded-full text-xs font-bold border ${getDifficultyBadge(
              problem.difficulty
            )}`}
          >
            {problem.difficulty}
          </span>
        </div>

        {problem.topic_tags && problem.topic_tags.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-line/40">
            <span className="text-xs text-gray-400 font-medium mr-1">Topics:</span>
            {problem.topic_tags.map((tag, idx) => (
              <span
                key={idx}
                className="px-2.5 py-1 rounded-lg bg-slate-800/80 text-teal-light text-xs border border-line/40 font-medium"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* SECTION 1: PROBLEM DESCRIPTION */}
      <div className="card-flat p-6 md:p-8 rounded-2xl bg-paper/90 border border-line/60 backdrop-blur-md shadow-md space-y-4">
        <div className="flex items-center gap-2.5 border-b border-line/40 pb-3">
          <BookOpen className="w-5 h-5 text-teal" />
          <h2 className="text-lg font-bold text-white">Problem Description</h2>
        </div>

        <LeetCodeRenderer content={problem.description_md} />
      </div>

      {/* SECTION 2: SOLUTION APPROACH & COMPLEXITY ANALYSIS (ACCORDION) */}
      <div className="card-flat rounded-2xl bg-paper/90 border border-line/60 backdrop-blur-md shadow-md overflow-hidden">
        <button
          onClick={() => setShowSolutionDropdown((prev) => !prev)}
          className="w-full flex items-center justify-between p-5 text-left bg-slate-900/60 hover:bg-slate-800/60 transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <Lightbulb className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">
                Solution Approach & Complexity Analysis
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Detailed intuition, algorithmic step breakdowns, and complexity proofs
              </p>
            </div>
          </div>
          {showSolutionDropdown ? (
            <ChevronUp className="w-5 h-5 text-gray-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-gray-400" />
          )}
        </button>

        {showSolutionDropdown && (
          <div className="p-6 md:p-8 border-t border-line/40 space-y-6">
            {approaches.length === 0 ? (
              <p className="text-sm text-gray-400 italic">
                Standard optimal approach available in the Code Implementation section below.
              </p>
            ) : (
              approaches.map((app, idx) => (
                <div
                  key={idx}
                  className="space-y-4 border-b border-line/40 pb-6 last:border-0 last:pb-0"
                >
                  <h3 className="text-base font-bold text-amber-300 flex items-center gap-2">
                    <span className="text-xs font-mono font-semibold px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
                      Approach {app.approach_index}
                    </span>
                    <span>{app.title}</span>
                  </h3>

                  {/* Complexity pills */}
                  <div className="flex flex-wrap items-center gap-3">
                    {app.time_complexity && (
                      <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-teal/10 border border-teal/20 text-teal text-xs font-mono font-medium">
                        <Clock className="w-3.5 h-3.5" />
                        <span>
                          Time:{" "}
                          <span
                            dangerouslySetInnerHTML={{
                              __html: formatLeetCodeMath(app.time_complexity),
                            }}
                          />
                        </span>
                      </div>
                    )}
                    {app.space_complexity && (
                      <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-mono font-medium">
                        <Cpu className="w-3.5 h-3.5" />
                        <span>
                          Space:{" "}
                          <span
                            dangerouslySetInnerHTML={{
                              __html: formatLeetCodeMath(app.space_complexity),
                            }}
                          />
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Explanation with math formatting */}
                  <div className="text-sm text-gray-300 leading-relaxed space-y-3">
                    <LeetCodeRenderer
                      content={app.explanation_md || app.intuition_md}
                    />
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* SECTION 3: MULTI-LANGUAGE CODE IMPLEMENTATION (ACCORDION) */}
      <div className="card-flat rounded-2xl bg-paper/90 border border-line/60 backdrop-blur-md shadow-md overflow-hidden">
        <button
          onClick={() => setShowCodeDropdown((prev) => !prev)}
          className="w-full flex items-center justify-between p-5 text-left bg-slate-900/60 hover:bg-slate-800/60 transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-teal/10 border border-teal/20 text-teal">
              <Code2 className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">
                Multi-Language Code Implementation
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Ready-to-run solutions in Python, Java, C++, TypeScript, Go, and JavaScript
              </p>
            </div>
          </div>
          {showCodeDropdown ? (
            <ChevronUp className="w-5 h-5 text-gray-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-gray-400" />
          )}
        </button>

        {showCodeDropdown && (
          <div className="p-6 md:p-8 border-t border-line/40 space-y-4">
            {codeData && codeData.languages.length > 0 ? (
              <>
                {/* Language Selector & Copy Button */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line/40 pb-4">
                  <div className="flex items-center gap-2">
                    <label className="text-xs font-semibold text-gray-400">
                      Language:
                    </label>
                    <select
                      value={selectedLanguage}
                      onChange={(e) => setSelectedLanguage(e.target.value)}
                      className="bg-slate-900 border border-line/60 rounded-xl px-3 py-1.5 text-xs text-teal font-mono font-semibold focus:outline-none focus:border-teal uppercase cursor-pointer"
                    >
                      {codeData.languages.map((lang) => (
                        <option key={lang} value={lang}>
                          {lang.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </div>

                  <button
                    onClick={() =>
                      handleCopyCode(codeData.solutions[selectedLanguage] || "")
                    }
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-gray-200 text-xs font-semibold border border-line/50 transition-colors cursor-pointer"
                  >
                    {copied ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-green" />
                        <span className="text-green">Copied!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5 text-gray-400" />
                        <span>Copy Code</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Code Viewer Box */}
                <div className="relative bg-slate-950 border border-line/60 rounded-xl p-4 overflow-x-auto font-mono text-xs text-slate-200 leading-relaxed shadow-inner">
                  <pre>
                    <code>
                      {codeData.solutions[selectedLanguage] ||
                        "// No code available for this language"}
                    </code>
                  </pre>
                </div>
              </>
            ) : (
              <p className="text-sm text-gray-400 italic">
                Code solutions are loading or being generated for this question.
              </p>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

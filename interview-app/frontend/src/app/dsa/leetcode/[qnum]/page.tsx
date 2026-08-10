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
} from "lucide-react";

interface ProblemDetail {
  qnum: number;
  title: string;
  slug: string;
  difficulty: "Easy" | "Medium" | "Hard";
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
  languages: string[];
  solutions: Record<string, string>;
}

export default function LeetCodeProblemDetailPage() {
  const params = useParams();
  const qnum = params?.qnum as string;

  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [approaches, setApproaches] = useState<Approach[]>([]);
  const [codeData, setCodeData] = useState<CodeData | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [showSolutionDropdown, setShowSolutionDropdown] = useState<boolean>(false);
  const [showCodeDropdown, setShowCodeDropdown] = useState<boolean>(false);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("python");
  const [copied, setCopied] = useState<boolean>(false);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    if (!qnum) return;
    fetchProblemDetail();
  }, [qnum]);

  const fetchProblemDetail = async () => {
    setLoading(true);
    try {
      // 1. Description ONLY (default view)
      const resProb = await fetch(`${API_BASE}/leetcode/problems/${qnum}`);
      if (resProb.ok) {
        const pData = await resProb.json();
        setProblem(pData);
      }

      // 2. Fetch Approaches for solution dropdown
      const resApp = await fetch(`${API_BASE}/leetcode/problems/${qnum}/approaches`);
      if (resApp.ok) {
        const aData = await resApp.json();
        setApproaches(aData || []);
      }

      // 3. Fetch Code snippets for code dropdown
      const resCode = await fetch(`${API_BASE}/leetcode/problems/${qnum}/code`);
      if (resCode.ok) {
        const cData = await resCode.json();
        setCodeData(cData);
        if (cData.languages && cData.languages.length > 0) {
          const pref = cData.languages.includes("python")
            ? "python"
            : cData.languages[0];
          setSelectedLanguage(pref);
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
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "medium":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "hard":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      default:
        return "bg-slate-500/10 text-slate-400 border-slate-500/20";
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0d1117] text-slate-100 p-8 flex flex-col items-center justify-center">
        <div className="animate-spin w-10 h-10 border-4 border-cyan-500 border-t-transparent rounded-full mb-4"></div>
        <p className="text-slate-400">Loading Problem #{qnum}...</p>
      </div>
    );
  }

  if (!problem) {
    return (
      <div className="min-h-screen bg-[#0d1117] text-slate-100 p-8 flex flex-col items-center justify-center">
        <p className="text-xl text-slate-400 mb-4">Problem #{qnum} not found.</p>
        <Link
          href="/dsa/leetcode"
          className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-medium transition-colors"
        >
          Back to LeetCode Explorer
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0d1117] text-slate-100 p-4 md:p-8 font-sans transition-all duration-300 md:pl-[calc(var(--sidebar-width)+1.5rem)]">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* Back Link */}
        <Link
          href="/dsa/leetcode"
          className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-cyan-400 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Back to LeetCode Explorer
        </Link>

        {/* Problem Header */}
        <div className="bg-[#161b22] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <span className="text-xs font-mono text-cyan-400 font-semibold tracking-wide">
                QUESTION #{problem.qnum}
              </span>
              <h1 className="text-2xl md:text-3xl font-bold text-white">
                {problem.title}
              </h1>
            </div>
            <span
              className={`self-start sm:self-auto px-3 py-1 rounded-full text-xs font-semibold border ${getDifficultyBadge(
                problem.difficulty
              )}`}
            >
              {problem.difficulty}
            </span>
          </div>

          <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-800/80">
            {problem.topic_tags.map((tag, idx) => (
              <span
                key={idx}
                className="px-2.5 py-1 rounded-md bg-slate-800/80 text-slate-300 text-xs border border-slate-700/60"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>

        {/* SECTION 1: PROBLEM DESCRIPTION (ALWAYS VISIBLE BY DEFAULT) */}
        <div className="bg-[#161b22] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
            <BookOpen className="w-5 h-5 text-cyan-400" />
            <h2 className="text-lg font-semibold text-white">Problem Description</h2>
          </div>

          <div className="prose prose-invert max-w-none text-slate-300 text-sm leading-relaxed overflow-x-auto">
            <div
              dangerouslySetInnerHTML={{ __html: problem.description_md }}
              className="space-y-3"
            />
          </div>
        </div>

        {/* SECTION 2: SOLUTION APPROACH DROPDOWN (ACCORDION) */}
        <div className="bg-[#161b22] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <button
            onClick={() => setShowSolutionDropdown((prev) => !prev)}
            className="w-full flex items-center justify-between p-5 text-left bg-slate-900/60 hover:bg-slate-800/60 transition-colors"
          >
            <div className="flex items-center gap-3">
              <Lightbulb className="w-5 h-5 text-amber-400" />
              <div>
                <h2 className="text-base font-semibold text-white">
                  Solution Approach & Complexity Analysis
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Click to {showSolutionDropdown ? "hide" : "reveal"} intuition, algorithms & $O(N)$ analysis
                </p>
              </div>
            </div>
            {showSolutionDropdown ? (
              <ChevronUp className="w-5 h-5 text-slate-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-slate-400" />
            )}
          </button>

          {showSolutionDropdown && (
            <div className="p-6 border-t border-slate-800 space-y-6">
              {approaches.length === 0 ? (
                <p className="text-sm text-slate-400">
                  No explicit approach notes available for this problem.
                </p>
              ) : (
                approaches.map((app, idx) => (
                  <div key={idx} className="space-y-3 border-b border-slate-800/60 pb-6 last:border-0 last:pb-0">
                    <h3 className="text-md font-semibold text-amber-300 flex items-center gap-2">
                      <span>Approach {app.approach_index}:</span> {app.title}
                    </h3>

                    {/* Complexity badges */}
                    <div className="flex flex-wrap items-center gap-3">
                      {app.time_complexity && (
                        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-mono">
                          <Clock className="w-3.5 h-3.5" />
                          <span>Time: {app.time_complexity}</span>
                        </div>
                      )}
                      {app.space_complexity && (
                        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-mono">
                          <Cpu className="w-3.5 h-3.5" />
                          <span>Space: {app.space_complexity}</span>
                        </div>
                      )}
                    </div>

                    <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
                      {app.explanation_md}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* SECTION 3: CODE IMPLEMENTATION DROPDOWN */}
        <div className="bg-[#161b22] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <button
            onClick={() => setShowCodeDropdown((prev) => !prev)}
            className="w-full flex items-center justify-between p-5 text-left bg-slate-900/60 hover:bg-slate-800/60 transition-colors"
          >
            <div className="flex items-center gap-3">
              <Code2 className="w-5 h-5 text-cyan-400" />
              <div>
                <h2 className="text-base font-semibold text-white">
                  Multi-Language Code Implementation
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Click to {showCodeDropdown ? "hide" : "reveal"} code solutions (Python, Java, C++, TypeScript, Go, etc.)
                </p>
              </div>
            </div>
            {showCodeDropdown ? (
              <ChevronUp className="w-5 h-5 text-slate-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-slate-400" />
            )}
          </button>

          {showCodeDropdown && (
            <div className="p-6 border-t border-slate-800 space-y-4">
              {codeData && codeData.languages.length > 0 ? (
                <>
                  {/* Language Selector Dropdown & Copy Button */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
                    <div className="flex items-center gap-2">
                      <label className="text-xs font-medium text-slate-400">
                        Select Language:
                      </label>
                      <select
                        value={selectedLanguage}
                        onChange={(e) => setSelectedLanguage(e.target.value)}
                        className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-cyan-300 font-mono focus:outline-none focus:border-cyan-500 uppercase"
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
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition-colors"
                    >
                      {copied ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span className="text-emerald-400">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>Copy Code</span>
                        </>
                      )}
                    </button>
                  </div>

                  {/* Code Viewer Box */}
                  <div className="relative bg-[#0d1117] border border-slate-800 rounded-xl p-4 overflow-x-auto font-mono text-xs text-slate-200 leading-relaxed">
                    <pre>
                      <code>{codeData.solutions[selectedLanguage] || "// No code available for this language"}</code>
                    </pre>
                  </div>
                </>
              ) : (
                <p className="text-sm text-slate-400">
                  No code solutions uploaded yet for this question.
                </p>
              )}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

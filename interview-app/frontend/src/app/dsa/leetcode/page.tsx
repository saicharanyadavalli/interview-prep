"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Search, Filter, BookOpen, CheckCircle, Award, ChevronLeft, ChevronRight } from "lucide-react";
import { CONFIG } from "@/lib/config";

interface LeetCodeProblem {
  qnum: number;
  title: string;
  slug: string;
  difficulty: "Easy" | "Medium" | "Hard";
  rating?: number;
  topic_tags: string[];
}

export default function LeetCodeExplorerPage() {
  const [problems, setProblems] = useState<LeetCodeProblem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [page, setPage] = useState<number>(1);
  const [total, setTotal] = useState<number>(0);
  const [search, setSearch] = useState<string>("");
  const [difficulty, setDifficulty] = useState<string>("");

  const API_BASE = CONFIG.API_BASE_URL;

  useEffect(() => {
    fetchProblems();
  }, [page, difficulty]);

  const fetchProblems = async (searchOverride?: string) => {
    setLoading(true);
    try {
      const qParams = new URLSearchParams({
        page: String(page),
        limit: "25",
      });
      if (difficulty) qParams.append("difficulty", difficulty);
      const querySearch = searchOverride !== undefined ? searchOverride : search;
      if (querySearch) qParams.append("search", querySearch);

      const res = await fetch(`${API_BASE}/leetcode/problems?${qParams.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setProblems(data.problems || []);
        setTotal(data.total || 0);
      }
    } catch (err) {
      console.error("Failed to load LeetCode problems:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchProblems();
  };

  const totalPages = Math.ceil(total / 25) || 1;

  const getDifficultyBadge = (diff: string) => {
    switch (diff.toLowerCase()) {
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

  return (
    <div className="min-h-screen bg-[#0d1117] text-slate-100 p-6 md:p-10 font-sans transition-all duration-300 md:pl-[calc(var(--sidebar-width)+1.5rem)]">
      <div className="max-w-7xl mx-auto space-y-8">
        
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-800 pb-6">
          <div>
            <div className="flex items-center gap-3">
              <BookOpen className="w-8 h-8 text-cyan-400" />
              <h1 className="text-3xl font-bold tracking-tight text-white">
                LeetCode DSA Question Bank
              </h1>
            </div>
            <p className="text-slate-400 text-sm mt-1">
              Explore 4,000+ Data Structures & Algorithms problems with descriptions, intuition breakdowns, and multi-language solutions.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="px-3 py-1.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-xs font-semibold">
              {total.toLocaleString()} Problems Available
            </span>
          </div>
        </div>

        {/* Filters & Search */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <form onSubmit={handleSearchSubmit} className="md:col-span-2 relative">
            <Search className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search by problem name or number (e.g. 1 or Two Sum)..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-[#161b22] border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors"
            />
          </form>

          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={difficulty}
              onChange={(e) => {
                setDifficulty(e.target.value);
                setPage(1);
              }}
              className="w-full bg-[#161b22] border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 transition-colors"
            >
              <option value="">All Difficulties</option>
              <option value="Easy">Easy</option>
              <option value="Medium">Medium</option>
              <option value="Hard">Hard</option>
            </select>
          </div>
        </div>

        {/* Problem List */}
        <div className="bg-[#161b22] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          {loading ? (
            <div className="p-12 text-center text-slate-400">
              <div className="inline-block animate-spin w-8 h-8 border-4 border-cyan-500 border-t-transparent rounded-full mb-3"></div>
              <p>Loading LeetCode problems...</p>
            </div>
          ) : problems.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              No problems found matching your query.
            </div>
          ) : (
            <div className="divide-y divide-slate-800/60">
              {problems.map((prob) => (
                <Link
                  key={prob.qnum}
                  href={`/dsa/leetcode/${prob.qnum}`}
                  className="group flex flex-col md:flex-row md:items-center justify-between p-4 hover:bg-slate-800/40 transition-colors gap-3"
                >
                  <div className="flex items-start gap-4">
                    <span className="text-xs font-mono text-slate-400 w-12 pt-0.5 font-bold">
                      #{prob.qnum}
                    </span>
                    <div>
                      <h3 className="text-base font-semibold text-slate-200 group-hover:text-cyan-400 transition-colors">
                        {prob.title}
                      </h3>
                      <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                        {prob.topic_tags.slice(0, 3).map((tag, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 text-[11px] border border-slate-700/50"
                          >
                            {tag}
                          </span>
                        ))}
                        {prob.topic_tags.length > 3 && (
                          <span className="text-[11px] text-slate-400">
                            +{prob.topic_tags.length - 3} more
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 pl-16 md:pl-0">
                    <span
                      className={`px-3 py-1 rounded-full text-xs font-semibold border ${getDifficultyBadge(
                        prob.difficulty
                      )}`}
                    >
                      {prob.difficulty}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between pt-4 text-sm text-slate-400 border-t border-slate-800">
          <div>
            Page <span className="text-slate-200 font-semibold">{page}</span> of{" "}
            <span className="text-slate-200 font-semibold">{totalPages}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(p - 1, 1))}
              className="p-2 rounded-lg bg-[#161b22] border border-slate-800 text-slate-300 disabled:opacity-40 hover:border-slate-700 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
              className="p-2 rounded-lg bg-[#161b22] border border-slate-800 text-slate-300 disabled:opacity-40 hover:border-slate-700 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}

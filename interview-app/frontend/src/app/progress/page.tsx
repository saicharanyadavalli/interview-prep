"use client";

import React, { useState, useEffect } from "react";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DifficultyRings } from "@/components/progress/DifficultyRings";
import { ConsistencyHeatmap } from "@/components/progress/ConsistencyHeatmap";
import { Milestones } from "@/components/progress/Milestones";
import { TopicInsights } from "@/components/progress/TopicInsights";
import { HistoryList } from "@/components/progress/HistoryList";
import { Spinner } from "@/components/Spinner";
import { Activity, BarChart2, History, AlertTriangle, BookOpen } from "lucide-react";
import Link from "next/link";

const DEFAULT_TOPIC_OPTIONS = [
  "Advanced Data Structure", "Algorithms", "anagram", "Arrays", "AVL-Tree", "Backtracking",
  "BFS", "Binary Indexed Tree", "Binary Representation", "Binary Search", "Binary Search Tree",
  "Bit Magic", "circular linked list", "circular-linked-list", "Combinatorial", "constructive algo",
  "CPP", "Data Structures", "Deque", "Design-Pattern", "DFS", "Disjoint Set", "Divide and Conquer",
  "Division", "doubly-linked-list", "Dynamic Programming", "factorial", "Fibonacci", "Game Theory",
  "Geometric", "Graph", "Greedy", "Hash", "Heap", "implementation", "Java", "Java-Collections",
  "Kadane", "LCS", "Linked List", "logical-thinking", "Machine Learning", "Map", "Mathematical",
  "Matrix", "Merge Sort", "Misc", "Modular Arithmetic", "number-theory", "Numbers", "palindrome",
  "Pattern Searching", "pattern-printing", "permutation", "Practice-Problems", "prefix-sum",
  "Prime Number", "priority-queue", "Queue", "Recursion", "Regular Expression", "Searching",
  "Segment-Tree", "series", "set", "Shortest Path", "sieve", "sliding-window", "Sorting", "Stack",
  "STL", "Strings", "subset", "topological-sort", "Traversal", "Tree", "Trie", "two-pointer-algorithm",
  "union-find"
];

function normalizeTopicKey(value: string) {
  return String(value || "").trim().toLowerCase();
}

function getFilterBuilderTopics() {
  const seen = new Set();
  const topics: any[] = [];

  DEFAULT_TOPIC_OPTIONS.forEach((topic) => {
    const label = String(topic || "").trim();
    const key = normalizeTopicKey(label);
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    topics.push({ topic_key: key, topic: label });
  });

  return topics;
}

function mergeTopicBreakdownWithFilterTopics(topicBreakdown: any[], filterTopics: any[]) {
  const backendMap = new Map();

  (Array.isArray(topicBreakdown) ? topicBreakdown : []).forEach((entry) => {
    const key = normalizeTopicKey(entry && entry.topic_key ? entry.topic_key : entry && entry.topic);
    if (!key) return;

    backendMap.set(key, {
      topic_key: key,
      topic: String((entry && entry.topic) || key),
      total_questions: Number((entry && entry.total_questions) || 0),
      solved_questions: Number((entry && entry.solved_questions) || 0),
      easy_total_questions: Number((entry && entry.easy_total_questions) || 0),
      medium_total_questions: Number((entry && entry.medium_total_questions) || 0),
      hard_total_questions: Number((entry && entry.hard_total_questions) || 0),
      easy_solved_questions: Number((entry && entry.easy_solved_questions) || 0),
      medium_solved_questions: Number((entry && entry.medium_solved_questions) || 0),
      hard_solved_questions: Number((entry && entry.hard_solved_questions) || 0),
    });
  });

  const filterList = Array.isArray(filterTopics) ? filterTopics : [];
  if (!filterList.length) {
    return Array.from(backendMap.values()).sort((a, b) => {
      const totalDelta = Number(b.total_questions || 0) - Number(a.total_questions || 0);
      if (totalDelta !== 0) return totalDelta;
      return String(a.topic || "").localeCompare(String(b.topic || ""));
    });
  }

  const merged = filterList
    .map((entry) => {
      const label = String(entry && entry.topic ? entry.topic : "").trim();
      const key = normalizeTopicKey(entry && entry.topic_key ? entry.topic_key : label);
      if (!key) return null;

      const backend = backendMap.get(key);
      if (backend) {
        return {
          ...backend,
          topic: label || backend.topic,
        };
      }

      return {
        topic_key: key,
        topic: label || key,
        total_questions: 0,
        solved_questions: 0,
        easy_total_questions: 0,
        medium_total_questions: 0,
        hard_total_questions: 0,
        easy_solved_questions: 0,
        medium_solved_questions: 0,
        hard_solved_questions: 0,
      };
    })
    .filter(Boolean)
    .filter((item: any) => Number(item.total_questions || 0) > 0 || Number(item.solved_questions || 0) > 0);

  return merged;
}

function buildAllTopicData(stats: any) {
  return {
    topic_key: "all",
    topic: "All topics",
    total_questions: Number(stats.total_questions || 0),
    solved_questions: Number(stats.solved_total_questions || 0),
    easy_total_questions: Number(stats.easy_total_questions || 0),
    medium_total_questions: Number(stats.medium_total_questions || 0),
    hard_total_questions: Number(stats.hard_total_questions || 0),
    easy_solved_questions: Number(stats.easy_solved_total_questions || 0),
    medium_solved_questions: Number(stats.medium_solved_total_questions || 0),
    hard_solved_questions: Number(stats.hard_solved_total_questions || 0),
  };
}

function deriveDifficultyStatsFromTopic(topicData: any) {
  return {
    easy: finalizeDifficultyStats(topicData?.easy_total_questions, topicData?.easy_solved_questions),
    medium: finalizeDifficultyStats(topicData?.medium_total_questions, topicData?.medium_solved_questions),
    hard: finalizeDifficultyStats(topicData?.hard_total_questions, topicData?.hard_solved_questions),
  };
}

function finalizeDifficultyStats(totalValue: number, solvedValue: number) {
  const total = Math.max(0, Number(totalValue || 0));
  const solved = Math.max(0, Number(solvedValue || 0));
  const percent = total > 0 ? Math.round((solved / total) * 100) : 0;

  return {
    attempted: total,
    solved,
    percent,
  };
}

export default function ProgressPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [stats, setStats] = useState<any>({});
  const [recent, setRecent] = useState<any[]>([]);
  const [allTopicData, setAllTopicData] = useState<any>({});
  const [topicBreakdown, setTopicBreakdown] = useState<any[]>([]);
  
  const [activeScope, setActiveScope] = useState("all");
  const [activeTopicKey, setActiveTopicKey] = useState("all");

  const [courseProgress, setCourseProgress] = useState<any[]>([]);
  const [loadingCourses, setLoadingCourses] = useState(true);

  useEffect(() => {
    let mounted = true;
    if (!user) {
      setLoading(false);
      setLoadingCourses(false);
      return;
    }
    
    
    API.getUserProgress()
      .then(data => {
        if (!mounted) return;
        const st = data?.stats || {};
        const rec = Array.isArray(data?.recent) ? data.recent : [];
        const rawTopics = Array.isArray(data?.topic_breakdown) ? data.topic_breakdown : [];
        
        setStats(st);
        setRecent(rec);
        
        const allData = buildAllTopicData(st);
        setAllTopicData(allData);
        
        const topics = mergeTopicBreakdownWithFilterTopics(rawTopics, getFilterBuilderTopics());
        setTopicBreakdown(topics);
        
        setLoading(false);
      })
      .catch(err => {
        if (mounted) {
          setError(err.message);
          setLoading(false);
        }
      });
      
    API.getLearningTracks().then(res => {
      if (!mounted) return;
      const tracks = res.tracks || [];
      Promise.all(
        tracks.map((t: any) => API.getLearningTrackProgress(t.track_id).catch(() => null))
      ).then(progressResults => {
        if (!mounted) return;
        const valid = progressResults.filter(Boolean);
        // attach display name from tracks
        const enriched = valid.map(p => {
          const t = tracks.find((tr: any) => tr.track_id === p.track_id);
          return { ...p, display_name: t?.display_name || p.track_id };
        });
        setCourseProgress(enriched);
        setLoadingCourses(false);
      });
    }).catch(() => {
      if (mounted) setLoadingCourses(false);
    });
      
    return () => { mounted = false; };
  }, [user]);

  if (!user) {
    return (
      <main className="main-content progress-main">
        <div className="empty-state">
          <p>Please sign in to view your progress.</p>
        </div>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="main-content progress-main">
        <Spinner text="Loading progress data..." />
      </main>
    );
  }

  if (error) {
    return (
      <main className="main-content progress-main">
        <div className="empty-state" style={{ padding: '3rem 2rem', textAlign: 'center', background: 'var(--bg)', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.75rem' }}>
            <AlertTriangle size={32} className="text-muted" />
          </div>
          <p>No progress data yet.</p>
          <p className="text-sm text-muted">{error}</p>
        </div>
      </main>
    );
  }
  
  const activeTopic = activeTopicKey === "all" 
    ? allTopicData 
    : (topicBreakdown.find((item) => normalizeTopicKey(item.topic_key) === activeTopicKey) || allTopicData);
    
  const difficultyStats = deriveDifficultyStatsFromTopic(activeTopic);
  const globalDifficultyStats = deriveDifficultyStatsFromTopic(allTopicData);

  const getSolvedBadgeText = () => {
    let solved = Number(activeTopic.solved_questions || 0);
    let total = Number(activeTopic.total_questions || 0);
    let suffix = "Solved";

    if (activeScope === "easy") {
      solved = Number(activeTopic.easy_solved_questions || 0);
      total = Number(activeTopic.easy_total_questions || 0);
      suffix = "Easy Solved";
    } else if (activeScope === "medium") {
      solved = Number(activeTopic.medium_solved_questions || 0);
      total = Number(activeTopic.medium_total_questions || 0);
      suffix = "Medium Solved";
    } else if (activeScope === "hard") {
      solved = Number(activeTopic.hard_solved_questions || 0);
      total = Number(activeTopic.hard_total_questions || 0);
      suffix = "Hard Solved";
    }
    return `${solved} / ${total} ${suffix}`;
  };

  return (
    <main className="main-content progress-main">
      <div className="page-header progress-header">
        <div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Activity size={28} className="text-teal" /> Immersive Progress Analytics
          </h1>
          <p className="card-subtitle progress-subtitle text-muted mt-2">Track difficulty-wise completion, consistency, and momentum.</p>
        </div>
      </div>

      <section className="progress-top-grid section" style={{ display: 'grid', gap: '1.5rem', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
        <article className="card-flat progress-rings-card">
          <div className="progress-card-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
            <h3 style={{ fontSize: '1.1rem' }}>Difficulty Completion</h3>
            <div className="progress-head-tools" style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
              <div id="difficultyScopeTabs" className="progress-scope-tabs" style={{ display: 'flex', background: 'var(--bg)', borderRadius: '1rem', padding: '0.2rem' }}>
                {[
                  { key: "all", label: "All" },
                  { key: "easy", label: "Easy" },
                  { key: "medium", label: "Medium" },
                  { key: "hard", label: "Hard" },
                ].map(scope => (
                  <button 
                    key={scope.key} 
                    type="button" 
                    className={`progress-scope-tab ${activeScope === scope.key ? "is-active" : ""}`} 
                    onClick={() => setActiveScope(scope.key)}
                    style={{ background: activeScope === scope.key ? 'var(--paper)' : 'transparent', color: activeScope === scope.key ? 'var(--ink)' : 'var(--muted)', padding: '0.3rem 0.8rem', borderRadius: '1rem', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: activeScope === scope.key ? 600 : 500, boxShadow: activeScope === scope.key ? '0 2px 4px rgba(0,0,0,0.05)' : 'none', transition: 'all 150ms ease' }}
                  >
                    {scope.label}
                  </button>
                ))}
              </div>
              <span id="attemptedBadge" className="counter-badge">{getSolvedBadgeText()}</span>
            </div>
          </div>
          <DifficultyRings stats={difficultyStats} activeScope={activeScope} />
        </article>

        <article className="card-flat progress-consistency-card">
          <div className="progress-card-head" style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ fontSize: '1.1rem' }}>Practice Consistency</h3>
          </div>
          <ConsistencyHeatmap recent={recent} />
        </article>
      </section>

      <section className="card-flat progress-milestones section">
        <div className="progress-card-head" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1.1rem' }}>Milestones</h3>
        </div>
        <Milestones stats={stats} difficultyStats={globalDifficultyStats} recent={recent} />
      </section>

      <section className="card-flat progress-topic section">
        <TopicInsights 
          topicBreakdown={topicBreakdown} 
          allTopicData={allTopicData} 
          activeTopicKey={activeTopicKey} 
          onTopicSelect={setActiveTopicKey} 
        />
      </section>

      <section className="section">
        <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <BookOpen size={20} className="text-teal" /> Course Progress
        </h3>
        
        {loadingCourses ? (
          <div className="card-flat" style={{ padding: '2rem', display: 'flex', justifyContent: 'center' }}>
            <Spinner text="Loading courses..." />
          </div>
        ) : courseProgress.length > 0 ? (
          <div className="grid gap-4 mt-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
            {courseProgress.map((course) => {
              const isPlaceholder = course.completion_percent === 0 && course.completed_steps === 0;
              return (
                <Link 
                  key={course.track_id} 
                  href={`/${course.track_id}`}
                  className={`card-flat block transition-all ${isPlaceholder ? 'opacity-60 hover:opacity-80' : 'hover-card'}`}
                  style={{ textDecoration: 'none' }}
                >
                  <div className="flex justify-between items-center mb-3">
                    <div className="flex items-center gap-2">
                      <h4 className="font-semibold text-white text-lg">{course.display_name}</h4>
                      {isPlaceholder && (
                        <span className="text-[10px] uppercase tracking-wider bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full border border-gray-700">
                          Coming Soon
                        </span>
                      )}
                    </div>
                    {!isPlaceholder && <span className="text-teal font-bold">{course.completion_percent}%</span>}
                  </div>
                  <div className="w-full bg-background rounded-full h-2 mb-2 overflow-hidden">
                    <div className={`h-full rounded-full ${isPlaceholder ? 'bg-gray-600' : 'bg-teal'}`} style={{ width: `${isPlaceholder ? 0 : course.completion_percent}%` }}></div>
                  </div>
                  <p className="text-xs text-gray-400">
                    {isPlaceholder 
                      ? "Content currently being prepared" 
                      : `${course.completed_steps} of ${course.total_steps} chapters completed`
                    }
                  </p>
                </Link>
              );
            })}
          </div>
        ) : (
          <p className="text-muted mt-2">No course data available.</p>
        )}
      </section>

      <section className="section">
        <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <History size={20} className="text-teal" /> Practice History
        </h3>
        <div id="historyList" className="progress-history-grid" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '1rem' }}>
          <HistoryList recent={recent} />
        </div>
      </section>
    </main>
  );
}

"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API } from "@/lib/api";
import Link from "next/link";
import {
  LayoutDashboard,
  TrendingUp,
  Clock,
  RotateCcw,
  CheckCircle2,
  Flame,
  Compass,
  Activity,
  ArrowRight
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { calculateStreak } from "@/components/progress/Milestones";
import { Spinner } from "@/components/Spinner";

export default function DashboardPage() {
  const router = useRouter();
  const { user, session, loading: authLoading } = useAuth();
  const [stats, setStats] = useState({
    total_attempted: 0,
    solved_count: 0,
    revisit_count: 0,
    current_streak: 0
  });
  const [recent, setRecent] = useState<any[] | null>(null);
  const [revisit, setRevisit] = useState<any[] | null>(null);
  const [loadingProgress, setLoadingProgress] = useState(true);
  const [loadingRevisit, setLoadingRevisit] = useState(true);

  useEffect(() => {
    if (authLoading) return;

    if (!user || !session) {
      router.replace("/login?next=/dashboard");
      return;
    }

    setLoadingProgress(true);
    setLoadingRevisit(true);

    Promise.allSettled([API.getUserProgress(true), API.getRevisitQueue()]).then(([progressResult, revisitResult]) => {
      if (progressResult.status === "fulfilled" && progressResult.value) {
        const receivedStats = progressResult.value.stats || {};
        const receivedRecent = progressResult.value.recent || [];
        const localStreak = calculateStreak(receivedRecent);
        const serverStreak = Number(receivedStats.current_streak || 0);
        const computedStreak = Math.max(serverStreak, localStreak);

        setStats({
          total_attempted: Number(receivedStats.total_attempted || 0),
          solved_count: Number(receivedStats.solved_count || 0),
          revisit_count: Number(receivedStats.revisit_count || 0),
          current_streak: computedStreak,
        });
        setRecent(receivedRecent);
      } else {
        setStats({ total_attempted: 0, solved_count: 0, revisit_count: 0, current_streak: 0 });
        setRecent([]);
      }
      setLoadingProgress(false);

      if (revisitResult.status === "fulfilled" && revisitResult.value) {
        setRevisit(revisitResult.value.items || []);
      } else {
        setRevisit([]);
      }
      setLoadingRevisit(false);
    }).catch(() => {
      setLoadingProgress(false);
      setLoadingRevisit(false);
    });
  }, [user, session, authLoading, router]);

  const renderRecentList = () => {
    if (loadingProgress) {
      return (
        <>
          {[1, 2, 3].map(i => (
            <div key={i} className="track-item" style={{ animation: 'pulse 1.5s infinite ease-in-out opacity 0.5' }}>
              <div className="track-item-main" style={{ width: '100%' }}>
                <div style={{ height: '18px', width: '60%', background: 'var(--line)', borderRadius: '4px', marginBottom: '8px' }}></div>
                <div style={{ height: '14px', width: '40%', background: 'var(--line)', borderRadius: '4px' }}></div>
              </div>
            </div>
          ))}
        </>
      );
    }

    if (!recent || recent.length === 0) {
      return (
        <div className="track-empty" style={{ textAlign: "center", padding: "2rem 1rem" }}>
          <p className="text-muted" style={{ marginBottom: "0.85rem" }}>No recent questions yet. Start practicing!</p>
          <Link href="/questions" className="btn btn-sm btn-primary">
            Browse Question Bank
          </Link>
        </div>
      );
    }

    const items = recent.slice(0, 8).map((entry, i) => {
      const isSolved = Boolean(entry.is_solved);
      const isRevisit = Boolean(entry.revisit);
      let statusLabel = "Not Solved";
      let color = "var(--muted)";

      if (isRevisit) {
        statusLabel = isSolved ? "Solved + Revisit" : "Revisit";
        color = "var(--amber)";
      } else if (isSolved) {
        statusLabel = "Solved";
        color = "var(--green)";
      }

      const metaParts = [entry.company, entry.difficulty].filter(Boolean).join(" · ");

      return (
        <div key={i} className="track-item">
          <div className="track-item-main">
            <Link
              href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`}
              className="track-title-link"
              style={{ textDecoration: "none", color: "inherit" }}
              aria-label={`Practice ${entry.question_title || entry.question_id}`}
            >
              <p className="track-title hover-text-teal">{entry.question_title || entry.question_id}</p>
            </Link>
            <p className="track-meta">
              {metaParts ? `${metaParts} · ` : ""}
              <span style={{ color, fontWeight: 600 }}>{statusLabel}</span>
            </p>
          </div>
          <Link
            href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`}
            className="btn btn-sm"
            aria-label={`Practice ${entry.question_title || entry.question_id}`}
          >
            Practice
          </Link>
        </div>
      );
    });

    return (
      <>
        {items}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--line)" }}>
          <Link href="/questions" className="text-teal text-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            Browse Question Bank <ArrowRight size={14} />
          </Link>
          <Link href="/progress" className="text-muted text-sm hover-text-teal" style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            View full history →
          </Link>
        </div>
      </>
    );
  };

  const renderRevisitPreview = () => {
    if (loadingRevisit) {
      return (
        <>
          {[1, 2].map(i => (
            <div key={i} className="track-item" style={{ animation: 'pulse 1.5s infinite ease-in-out opacity 0.5' }}>
              <div className="track-item-main" style={{ width: '100%' }}>
                <div style={{ height: '18px', width: '60%', background: 'var(--line)', borderRadius: '4px', marginBottom: '8px' }}></div>
                <div style={{ height: '14px', width: '40%', background: 'var(--line)', borderRadius: '4px' }}></div>
              </div>
            </div>
          ))}
        </>
      );
    }

    if (!revisit || revisit.length === 0) {
      return (
        <div className="track-empty" style={{ textAlign: "center", padding: "2rem 1rem" }}>
          <p className="text-muted" style={{ marginBottom: "0.85rem" }}>No questions in your revisit queue.</p>
          <Link href="/questions" className="text-teal text-sm">
            Add questions from Question Bank →
          </Link>
        </div>
      );
    }

    const items = revisit.slice(0, 5).map((entry, i) => {
      const metaParts = [entry.company, entry.difficulty].filter(Boolean).join(" · ");
      return (
        <div key={i} className="track-item">
          <div className="track-item-main">
            <Link
              href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`}
              className="track-title-link"
              style={{ textDecoration: "none", color: "inherit" }}
              aria-label={`Practice question ${entry.question_title || entry.qnum}`}
            >
              <p className="track-title hover-text-teal">{entry.question_title || `Question #${entry.qnum || ""}`}</p>
            </Link>
            <p className="track-meta">{metaParts || "General Practice"}</p>
          </div>
          <Link
            href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`}
            className="btn btn-sm"
            aria-label={`Practice question ${entry.question_title || entry.qnum}`}
          >
            Practice
          </Link>
        </div>
      );
    });

    return (
      <>
        {items}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--line)" }}>
          <Link href="/revisit" className="text-teal text-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            View all {revisit.length} in queue <ArrowRight size={14} />
          </Link>
        </div>
      </>
    );
  };

  if (authLoading || !user || !session) {
    return (
      <main className="main-content" style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Spinner text="Loading dashboard..." />
      </main>
    );
  }

  return (
    <main className="main-content">
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem" }}>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <LayoutDashboard size={28} className="text-teal" /> Dashboard
        </h1>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <Link href="/questions" className="btn btn-sm btn-primary" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            <Compass size={16} /> Browse Questions
          </Link>
          <Link href="/progress" className="btn btn-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            <Activity size={16} /> Analytics
          </Link>
        </div>
      </div>

      <section className="section">
        <h3 className="section-title">
          <TrendingUp size={20} className="text-teal" /> Your Progress
        </h3>
        {loadingProgress ? (
          <div id="statsGrid" className="stats-grid">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="stat-card skeleton-card" style={{ height: '90px', background: 'var(--paper)', border: '1px solid var(--line)', animation: 'pulse 1.5s infinite ease-in-out opacity 0.5' }}></div>
            ))}
          </div>
        ) : (
          <div id="statsGrid" className="stats-grid">
            <Link
              href="/questions"
              className="stat-card attempted animate-slide"
              style={{ animationDelay: "0ms", textDecoration: "none", cursor: "pointer" }}
              title="View all questions"
              aria-label="View all questions"
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <p className="stat-label">Total Attempted</p>
                  <p className="stat-value">{stats.total_attempted}</p>
                </div>
                <TrendingUp size={24} className="text-teal" style={{ opacity: 0.8 }} />
              </div>
            </Link>

            <Link
              href="/questions?status=solved"
              className="stat-card solved animate-slide"
              style={{ animationDelay: "60ms", textDecoration: "none", cursor: "pointer" }}
              title="View solved questions"
              aria-label="View solved questions"
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <p className="stat-label">Solved</p>
                  <p className="stat-value" style={{ color: "var(--green)" }}>{stats.solved_count}</p>
                </div>
                <CheckCircle2 size={24} style={{ color: "var(--green)", opacity: 0.8 }} />
              </div>
            </Link>

            <Link
              href="/revisit"
              className="stat-card revisit animate-slide"
              style={{ animationDelay: "120ms", textDecoration: "none", cursor: "pointer" }}
              title="Open revisit queue"
              aria-label="Open revisit queue"
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <p className="stat-label">Revisit Queue</p>
                  <p className="stat-value" style={{ color: "var(--amber)" }}>{stats.revisit_count}</p>
                </div>
                <RotateCcw size={24} style={{ color: "var(--amber)", opacity: 0.8 }} />
              </div>
            </Link>

            <Link
              href="/progress"
              className="stat-card streak animate-slide"
              style={{ animationDelay: "180ms", textDecoration: "none", cursor: "pointer" }}
              title="View consistency heatmap & streak"
              aria-label="View consistency heatmap & streak"
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <p className="stat-label">Streaks</p>
                  <p className="stat-value" style={{ color: "var(--teal)" }}>
                    {stats.current_streak}{" "}
                    <span style={{ fontSize: "1rem", fontWeight: 500, color: "var(--muted)" }}>
                      {stats.current_streak === 1 ? "day" : "days"}
                    </span>
                  </p>
                </div>
                <Flame size={24} style={{ color: "var(--teal)", opacity: 0.8 }} />
              </div>
            </Link>
          </div>
        )}
      </section>

      <div className="two-col">
        <section className="section">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <h3 className="section-title" style={{ margin: 0 }}>
              <Link
                href="/questions"
                className="section-title-link"
                style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", color: "inherit", textDecoration: "none" }}
                title="View question bank"
                aria-label="Recently Attempted - View questions"
              >
                <Clock size={20} className="text-teal" /> Recently Attempted
              </Link>
            </h3>
            <Link
              href="/questions"
              className="text-sm text-teal hover-text-teal"
              style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
              title="View all questions"
            >
              View all <ArrowRight size={14} />
            </Link>
          </div>
          <div className="card-flat">
            <div id="recentList" className="track-list">
              {renderRecentList()}
            </div>
          </div>
        </section>

        <section className="section">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <h3 className="section-title" style={{ margin: 0 }}>
              <Link
                href="/revisit"
                className="section-title-link"
                style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", color: "inherit", textDecoration: "none" }}
                title="Open revisit queue"
                aria-label="Revisit Queue - Open revisit list"
              >
                <RotateCcw size={20} className="text-teal" /> Revisit Queue
              </Link>
            </h3>
            <Link
              href="/revisit"
              className="text-sm text-teal hover-text-teal"
              style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
              title="View all revisit questions"
            >
              View queue <ArrowRight size={14} />
            </Link>
          </div>
          <div className="card-flat">
            <div id="revisitPreview" className="track-list">
              {renderRevisitPreview()}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

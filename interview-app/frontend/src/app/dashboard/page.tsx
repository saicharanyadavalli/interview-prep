"use client";

import React, { useEffect, useState } from "react";
import { API } from "@/lib/api";
import Link from "next/link";
import { LayoutDashboard, TrendingUp, Clock, RotateCcw } from "lucide-react";
import { Spinner } from "@/components/Spinner";
import { useAuth } from "@/lib/auth";

export default function DashboardPage() {
  const { user, session } = useAuth();
  const [stats, setStats] = useState({ total_attempted: 0, revisit_count: 0 });
  const [recent, setRecent] = useState<any[] | null>(null);
  const [revisit, setRevisit] = useState<any[] | null>(null);
  const [loadingProgress, setLoadingProgress] = useState(true);
  const [loadingRevisit, setLoadingRevisit] = useState(true);

  useEffect(() => {
    if (!user || !session) return;
    
    // Sync session with backend as legacy dashboard.js did
    API._fetch("/auth/session", {
      method: "POST",
      body: JSON.stringify({ access_token: session.access_token }),
    }).catch(() => {}); // Ignore sync errors

    Promise.allSettled([API.getUserProgress(true), API.getRevisitQueue()]).then(([progressResult, revisitResult]) => {
      if (progressResult.status === "fulfilled") {
        setStats(progressResult.value.stats || { total_attempted: 0, revisit_count: 0 });
        setRecent(progressResult.value.recent || []);
      } else {
        setStats({ total_attempted: 0, revisit_count: 0 });
        setRecent([]);
      }
      setLoadingProgress(false);

      if (revisitResult.status === "fulfilled") {
        setRevisit(revisitResult.value.items || []);
      } else {
        setRevisit([]);
      }
      setLoadingRevisit(false);
    });
  }, [user, session]);

  const renderRecentList = () => {
    if (loadingProgress) return (
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
    if (!recent || recent.length === 0) {
      return <p className="track-empty">No recent questions yet. Start practicing!</p>;
    }

    return recent.slice(0, 8).map((entry, i) => {
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

      return (
        <div key={i} className="track-item">
          <div className="track-item-main">
            <p className="track-title">{entry.question_title || entry.question_id}</p>
            <p className="track-meta">
              {entry.company} · {entry.difficulty} · <span style={{ color, fontWeight: 600 }}>{statusLabel}</span>
            </p>
          </div>
          <Link href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`} className="btn btn-sm">
            Practice
          </Link>
        </div>
      );
    });
  };

  const renderRevisitPreview = () => {
    if (loadingRevisit) return (
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
    if (!revisit || revisit.length === 0) {
      return <p className="track-empty">No questions in your revisit queue.</p>;
    }

    const items = revisit.slice(0, 5).map((entry, i) => (
      <div key={i} className="track-item">
        <div className="track-item-main">
          <p className="track-title">{entry.question_title || `Question #${entry.qnum || ""}`}</p>
          <p className="track-meta">{entry.company} · {entry.difficulty}</p>
        </div>
        <Link href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`} className="btn btn-sm">
          Practice
        </Link>
      </div>
    ));

    return (
      <>
        {items}
        {revisit.length > 5 && (
          <Link href="/revisit" className="text-teal text-sm block mt-2" style={{ display: "block", marginTop: "0.5rem" }}>
            View all {revisit.length} items →
          </Link>
        )}
      </>
    );
  };

  return (
    <main className="main-content">
      <div className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <LayoutDashboard size={28} className="text-teal" /> Dashboard
        </h1>
      </div>

      <section className="section">
        <h3 className="section-title">
          <TrendingUp size={20} className="text-teal" /> Your Progress
        </h3>
        {loadingProgress ? (
          <div id="statsGrid" className="stats-grid">
            <div className="stat-card skeleton-card" style={{ height: '90px', background: 'var(--paper)', border: '1px solid var(--line)', animation: 'pulse 1.5s infinite ease-in-out opacity 0.5' }}></div>
            <div className="stat-card skeleton-card" style={{ height: '90px', background: 'var(--paper)', border: '1px solid var(--line)', animation: 'pulse 1.5s infinite ease-in-out opacity 0.5' }}></div>
          </div>
        ) : (
          <div id="statsGrid" className="stats-grid">
            <div className="stat-card attempted animate-slide" style={{ animationDelay: "0ms" }}>
              <p className="stat-label">Total Attempted</p>
              <p className="stat-value">{stats.total_attempted}</p>
            </div>
            <div className="stat-card revisit animate-slide" style={{ animationDelay: "80ms" }}>
              <p className="stat-label">Revisit</p>
              <p className="stat-value">{stats.revisit_count}</p>
            </div>
          </div>
        )}
      </section>

      <div className="two-col">
        <section className="section">
          <h3 className="section-title">
            <Clock size={20} className="text-teal" /> Recently Attempted
          </h3>
          <div className="card-flat">
            <div id="recentList" className="track-list">
              {renderRecentList()}
            </div>
          </div>
        </section>

        <section className="section">
          <h3 className="section-title">
            <RotateCcw size={20} className="text-teal" /> Revisit Queue
          </h3>
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

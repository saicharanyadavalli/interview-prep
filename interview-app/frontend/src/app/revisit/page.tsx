"use client";

import React, { useState, useEffect } from "react";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/Spinner";
import { RotateCcw, AlertTriangle, ClipboardList } from "lucide-react";
import Link from "next/link";

function normalizeDifficulty(value: string) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "easy" || text === "medium" || text === "hard") return text;
  return "unknown";
}

function titleCase(value: string) {
  return String(value || "")
    .toLowerCase()
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDate(dateStr: string) {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return String(dateStr);
  }
}

export default function RevisitPage() {
  const { user } = useAuth();
  
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [toastMsg, setToastMsg] = useState("");
  const [toastType, setToastType] = useState("info");
  const [showToast, setShowToast] = useState(false);
  const [removingIds, setRemovingIds] = useState<Set<number>>(new Set());

  const displayToast = (msg: string, type = "info") => {
    setToastMsg(msg);
    setToastType(type);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2600);
  };

  const loadQueue = async () => {
    try {
      const data = await API.getRevisitQueue();
      const loaded = Array.isArray(data?.items) ? data.items : [];
      setItems(loaded);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    if (!user) {
      if (mounted) setLoading(false);
      return;
    }
    
    API.getRevisitQueue().then(data => {
      if (!mounted) return;
      const loaded = Array.isArray(data?.items) ? data.items : [];
      setItems(loaded);
      setLoading(false);
    }).catch(err => {
      if (mounted) {
        setError(err.message);
        setLoading(false);
      }
    });
    
    return () => { mounted = false; };
  }, [user]);

  const handleRemove = async (qnum: number) => {
    setRemovingIds(prev => new Set(prev).add(qnum));
    try {
      await API.removeFromRevisit(String(qnum));
      displayToast("Removed from revisit queue.", "success");
      await loadQueue();
    } catch (err: any) {
      displayToast(`Failed to remove: ${err.message}`, "error");
    } finally {
      setRemovingIds(prev => {
        const next = new Set(prev);
        next.delete(qnum);
        return next;
      });
    }
  };

  const summarizeQueue = () => {
    const summary = { total: 0, easy: 0, medium: 0, hard: 0 };
    items.forEach((entry) => {
      summary.total += 1;
      const difficulty = normalizeDifficulty(entry?.difficulty);
      if (difficulty === "easy") summary.easy += 1;
      if (difficulty === "medium") summary.medium += 1;
      if (difficulty === "hard") summary.hard += 1;
    });
    return summary;
  };

  if (!user) {
    return (
      <main className="main-content revisit-v3-main">
        <div className="empty-state">
          <p>Please sign in to view your revisit queue.</p>
        </div>
      </main>
    );
  }

  const summary = summarizeQueue();

  return (
    <main className="main-content revisit-v3-main">
      {showToast && (
        <div id="toast" className={`toast toast-${toastType} toast-show`}>
          {toastMsg}
        </div>
      )}

      <div className="page-header revisit-header">
        <div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <RotateCcw size={28} className="text-teal" /> Revisit Queue
          </h1>
          <p className="card-subtitle text-muted mt-2">Questions you flagged for another attempt. Keep this queue lean and focused.</p>
        </div>
        <div className="page-header-actions">
          <span className="counter-badge">{summary.total}</span>
        </div>
      </div>

      <section className="revisit-stats section stats-grid">
        <article className="stat-card attempted">
          <p className="stat-label">Queue Size</p>
          <p className="stat-value">{summary.total}</p>
        </article>
        <article className="stat-card">
          <p className="stat-label">Easy</p>
          <p className="stat-value">{summary.easy}</p>
        </article>
        <article className="stat-card">
          <p className="stat-label">Medium</p>
          <p className="stat-value">{summary.medium}</p>
        </article>
        <article className="stat-card revisit">
          <p className="stat-label">Hard</p>
          <p className="stat-value">{summary.hard}</p>
        </article>
      </section>

      <section className="card-flat revisit-list-card">
        <div className="revisit-list" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {loading && <Spinner text="Loading revisit queue..." />}
          
          {!loading && error && (
            <div className="empty-state" style={{ padding: '3rem 2rem', textAlign: 'center', background: 'var(--bg)', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.75rem' }}>
                <AlertTriangle size={32} className="text-muted" />
              </div>
              <p>Could not load revisit queue.</p>
              <p className="text-sm text-muted">{error}</p>
            </div>
          )}

          {!loading && !error && items.length === 0 && (
            <div className="empty-state" style={{ padding: '3rem 2rem', textAlign: 'center', background: 'var(--bg)', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.75rem' }}>
                <ClipboardList size={32} className="text-muted" />
              </div>
              <p>Your revisit queue is empty.</p>
              <p className="text-sm text-muted">Mark questions as Revisit while practicing to bring them here.</p>
            </div>
          )}

          {!loading && !error && items.length > 0 && items.map((entry, index) => {
            const difficulty = normalizeDifficulty(entry?.difficulty);
            const difficultyLabel = titleCase(difficulty || "unknown");
            const qnum = Number(entry?.qnum || 0);
            const isRemoving = removingIds.has(qnum);

            return (
              <article key={qnum} className={`revisit-item diff-${difficulty}`} style={{ padding: '1.25rem', background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 'var(--radius)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <div className="revisit-item-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <h3 style={{ fontSize: '1.05rem', margin: 0 }}>{index + 1}. {entry.question_title || `Question #${qnum}`}</h3>
                  <span className={`pill revisit-diff-pill ${difficulty}`} style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.6rem', borderRadius: '1rem', fontSize: '0.75rem' }}>{difficultyLabel}</span>
                </div>

                <p className="revisit-item-meta text-muted text-sm" style={{ marginBottom: '0.5rem' }}>
                  {entry.company || "Unknown Company"}
                  {entry.added_at ? ` • Added ${formatDate(entry.added_at)}` : ""}
                </p>

                <div className="revisit-actions" style={{ display: 'flex', gap: '0.5rem' }}>
                  <Link href={`/solve?qnum=${encodeURIComponent(qnum)}`} className="btn btn-sm btn-primary">Practice Now</Link>
                  <button 
                    className="btn btn-sm btn-danger" 
                    onClick={() => handleRemove(qnum)}
                    disabled={isRemoving}
                    style={{ background: 'transparent', border: '1px solid var(--red)', color: 'var(--red)' }}
                  >
                    {isRemoving ? "Removing..." : "Remove"}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}

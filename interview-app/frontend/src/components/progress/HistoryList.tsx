import React from "react";
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
  if (!dateStr) return "Date unavailable";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return String(dateStr);
  }
}

export function HistoryList({ recent }: { recent: any[] }) {
  if (!Array.isArray(recent) || !recent.length) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center bg-surface border border-line rounded-lg relative z-10 w-full mt-4">
        <p className="text-4xl mb-3">📝</p>
        <p className="text-gray-400">No practice history yet. Start solving questions to populate this timeline.</p>
      </div>
    );
  }

  return (
    <>
      {recent.map((entry, idx) => {
        const difficulty = normalizeDifficulty(entry && entry.difficulty);
        const difficultyLabel = titleCase(difficulty || "unknown");

        const solved = Boolean(entry && entry.is_solved);
        const revisit = Boolean(entry && entry.revisit);

        let statusClass = "not-solved";
        let statusLabel = "Not Solved";
        if (revisit && solved) {
          statusClass = "revisit";
          statusLabel = "Solved + Revisit";
        } else if (revisit) {
          statusClass = "revisit";
          statusLabel = "Revisit";
        } else if (solved) {
          statusClass = "solved";
          statusLabel = "Solved";
        }

        return (
          <article key={idx} className={`progress-v3-history-card diff-${difficulty}`}>
            <div className="progress-v3-history-head">
              <h4>{entry.question_title || entry.question_id || "Untitled Question"}</h4>
              <span className={`pill progress-v3-diff-pill ${difficulty}`}>{difficultyLabel}</span>
            </div>
            <p className="progress-v3-history-meta">{entry.company || "Unknown Company"} • {formatDate(entry.updated_at)}</p>
            <p className={`progress-v3-history-status ${statusClass}`}>{statusLabel}</p>
            <div className="progress-v3-history-actions">
              <Link href={`/solve?qnum=${encodeURIComponent(entry.qnum || "")}`} className="btn btn-sm btn-primary">Practice Again</Link>
            </div>
          </article>
        );
      })}
    </>
  );
}

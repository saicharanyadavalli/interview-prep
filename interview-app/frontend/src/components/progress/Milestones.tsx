import React from "react";
import { calculateStreak } from "@/utils/streak-analytics";

export { calculateStreak };

export function Milestones({
  stats,
  difficultyStats,
  recent,
}: {
  stats: any;
  difficultyStats: any;
  recent: any[];
}) {
  const safeStats = stats || {};
  const safeDiff = difficultyStats || {};
  const safeRecent = Array.isArray(recent) ? recent : [];

  const totalAttempted = Number(safeStats.total_attempted || 0);
  const solvedCount = Number(safeStats.solved_count || 0);
  const revisitCount = Number(safeStats.revisit_count || 0);

  const localStreak = calculateStreak(safeRecent);
  const serverStreak = Number(safeStats.current_streak || 0);
  const streak = Math.max(serverStreak, localStreak);

  const totalDifficultySolved =
    Number((safeDiff.easy && safeDiff.easy.solved) || 0) +
    Number((safeDiff.medium && safeDiff.medium.solved) || 0) +
    Number((safeDiff.hard && safeDiff.hard.solved) || 0);

  const totalQuestions = Number(safeStats.total_questions || 100);
  const goalSolved = Math.max(0, solvedCount);

  const milestones = [
    {
      label: "10 Attempts",
      sublabel: `${Math.min(totalAttempted, 10)} / 10`,
      unlocked: totalAttempted >= 10,
      progress: Math.min(100, (totalAttempted / 10) * 100),
    },
    {
      label: "25 Solved",
      sublabel: `${Math.min(solvedCount, 25)} / 25`,
      unlocked: solvedCount >= 25,
      progress: Math.min(100, (solvedCount / 25) * 100),
    },
    {
      label: "3-Day Streak",
      sublabel: `${Math.min(streak, 3)} / 3`,
      unlocked: streak >= 3,
      progress: Math.min(100, (streak / 3) * 100),
    },
    {
      label: "Queue Control",
      sublabel: revisitCount <= 5 ? "Under 5" : `${revisitCount} in queue`,
      unlocked: revisitCount <= 5,
      progress: revisitCount <= 5 ? 100 : Math.max(0, 100 - revisitCount * 5),
    },
    {
      label: "Difficulty Master",
      sublabel: `${totalDifficultySolved} solved`,
      unlocked: totalDifficultySolved >= 15,
      progress: Math.min(100, (totalDifficultySolved / 15) * 100),
    },
    {
      label: "Solved Goal",
      sublabel: `${goalSolved} / ${totalQuestions > 0 ? totalQuestions : 100}`,
      unlocked: goalSolved >= (totalQuestions > 0 ? totalQuestions : 100),
      progress: totalQuestions > 0 ? Math.min(100, (goalSolved / totalQuestions) * 100) : 0,
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4">
      {milestones.map((item, idx) => {
        let badge;
        if (item.unlocked) {
          badge = (
            <span className="text-teal bg-teal/10 border border-teal/20 px-2 py-0.5 rounded-full text-xs font-medium">
              Unlocked
            </span>
          );
        } else if (item.progress > 0) {
          badge = (
            <span className="text-amber bg-amber/10 border border-amber/20 px-2 py-0.5 rounded-full text-xs font-medium">
              In Progress
            </span>
          );
        } else {
          badge = (
            <span className="text-muted bg-muted/10 border border-muted/20 px-2 py-0.5 rounded-full text-xs font-medium">
              Locked
            </span>
          );
        }

        return (
          <article
            key={idx}
            style={{
              padding: "1.5rem",
              borderRadius: "var(--radius-lg)",
              border: item.unlocked
                ? "1px solid rgba(20, 184, 166, 0.3)"
                : "1px solid var(--line)",
              backgroundColor: item.unlocked ? "rgba(20, 184, 166, 0.05)" : "var(--paper)",
              display: "flex",
              flexDirection: "column",
              height: "100%",
              transition: "all 200ms ease",
            }}
          >
            <div className="flex justify-between items-start mb-6">
              <h4
                className={`font-semibold text-sm md:text-base ${
                  item.unlocked ? "text-teal" : "text-white"
                }`}
              >
                {item.label}
              </h4>
              {badge}
            </div>

            <div className="mt-auto">
              <div
                style={{
                  width: "100%",
                  backgroundColor: "var(--line)",
                  borderRadius: "9999px",
                  height: "8px",
                  overflow: "hidden",
                  marginBottom: "0.5rem",
                }}
              >
                <div
                  style={{
                    width: `${Math.max(0, Math.min(100, item.progress || 0))}%`,
                    height: "100%",
                    borderRadius: "9999px",
                    transition: "width 500ms ease-in-out",
                    backgroundColor: item.unlocked ? "var(--teal)" : "var(--muted)",
                    boxShadow: item.unlocked ? "0 0 8px var(--teal)" : "none",
                  }}
                ></div>
              </div>
              <div className="flex justify-between items-center text-xs text-gray-400">
                <span>Progress</span>
                <span className="font-medium text-gray-300">{item.sublabel}</span>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

import React from "react";

export function DifficultyRings({ stats, activeScope }: { stats: any; activeScope: string }) {
  const ringConfigs = [
    { key: "easy", label: "Easy", className: "easy" },
    { key: "medium", label: "Medium", className: "medium" },
    { key: "hard", label: "Hard", className: "hard" },
  ];

  const radius = 54;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="progress-v3-rings-wrap">
      {ringConfigs.map((config) => {
        const item = stats[config.key] || { attempted: 0, solved: 0, percent: 0 };
        const progress = Math.max(0, Math.min(100, Number(item.percent || 0))) / 100;
        const dashOffset = circumference * (1 - progress);
        const isMuted = activeScope !== "all" && activeScope !== config.key;

        const colors: Record<string, string> = {
          easy: "var(--green)",
          medium: "var(--amber)",
          hard: "var(--red)",
        };
        const strokeColor = colors[config.key] || "var(--teal)";

        return (
          <article key={config.key} className={`progress-v3-ring-card ${config.className} ${isMuted ? "is-muted" : ""}`} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div className="progress-v3-ring" role="img" aria-label={`${config.label} solved ${item.solved} out of ${item.attempted}`} style={{ position: 'relative', width: '140px', height: '140px', margin: '0 auto 1rem' }}>
              <svg viewBox="0 0 140 140" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
                <circle 
                  className="ring-bg" 
                  cx="70" cy="70" r={radius} 
                  fill="none" 
                  stroke="var(--line)" 
                  strokeWidth="12"
                ></circle>
                <circle
                  className="ring-fill"
                  cx="70"
                  cy="70"
                  r={radius}
                  fill="none"
                  stroke={strokeColor}
                  strokeWidth="12"
                  strokeLinecap="round"
                  strokeDasharray={circumference.toFixed(2)}
                  strokeDashoffset={dashOffset.toFixed(2)}
                  style={{ transition: 'stroke-dashoffset 0.5s ease-in-out' }}
                ></circle>
              </svg>
              <div className="progress-v3-ring-center" style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                <p className="progress-v3-ring-value" style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, lineHeight: 1.2, color: 'var(--ink)' }}>{item.solved}</p>
                <p className="progress-v3-ring-unit" style={{ fontSize: '0.8rem', color: 'var(--muted)', margin: 0 }}>Solved</p>
              </div>
            </div>
            <p className="progress-v3-ring-title" style={{ fontWeight: 600, fontSize: '1.05rem', margin: '0 0 0.25rem' }}>{config.label}</p>
            <p className="progress-v3-ring-meta" style={{ fontSize: '0.85rem', color: 'var(--muted)', margin: 0 }}>{item.solved}/{item.attempted} completed • {item.percent}%</p>
          </article>
        );
      })}
    </div>
  );
}

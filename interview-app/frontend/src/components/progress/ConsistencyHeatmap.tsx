import React from "react";

function toDateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDate(dateStr: string) {
  if (!dateStr) return "Date unavailable";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return String(dateStr);
  }
}

function buildActivityMap(recent: any[]) {
  const map: Record<string, number> = {};
  (Array.isArray(recent) ? recent : []).forEach((entry) => {
    if (!entry || !entry.updated_at) return;
    const parsed = new Date(entry.updated_at);
    if (Number.isNaN(parsed.getTime())) return;

    parsed.setHours(0, 0, 0, 0);
    const key = toDateKey(parsed);
    map[key] = Number(map[key] || 0) + 1;
  });
  return map;
}

function getIntensityClass(intensity: number) {
  switch (intensity) {
    case 0: return "bg-gray-800/60";
    case 1: return "bg-teal-900/80";
    case 2: return "bg-teal-700/80";
    case 3: return "bg-teal-500";
    case 4: return "bg-teal-400";
    default: return "bg-gray-800/60";
  }
}

export function ConsistencyHeatmap({ recent }: { recent: any[] }) {
  const countsByDate = buildActivityMap(recent);
  const totalDays = 30;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const cells = [];
  for (let offset = totalDays - 1; offset >= 0; offset -= 1) {
    const date = new Date(today);
    date.setDate(today.getDate() - offset);
    const key = toDateKey(date);
    const attempts = Number(countsByDate[key] || 0);
    const intensity = Math.min(4, attempts);

    cells.push(
      <div
        key={key}
        className={`w-full aspect-square rounded-sm ${getIntensityClass(intensity)} transition-colors duration-200 hover:ring-1 hover:ring-teal-300 cursor-default`}
        title={`${formatDate(date.toISOString())}: ${attempts} practice session${attempts === 1 ? "" : "s"}`}
      ></div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div 
        className="grid grid-cols-[repeat(10,minmax(0,1fr))] gap-1.5 sm:gap-2" 
        aria-label="Last 30 days activity"
      >
        {cells}
      </div>
      <div className="flex flex-wrap items-center justify-between text-sm text-muted mt-2 gap-4">
        <span>Past 30 days</span>
        <div className="flex items-center gap-1.5 text-xs">
          <span>Less</span>
          <div className="w-3 h-3 rounded-sm bg-gray-800/60"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-900/80"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-700/80"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-500"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-400"></div>
          <span>More</span>
        </div>
      </div>
    </div>
  );
}


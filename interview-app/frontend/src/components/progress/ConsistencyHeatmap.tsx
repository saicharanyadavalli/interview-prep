"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { Calendar, Activity, X } from "lucide-react";
import {
  toDateKey,
  formatDateDisplay,
  buildHeatmapDays,
  calculateDayActivity,
  calculate30DaySummary,
  normalizeDifficulty,
} from "@/utils/streak-analytics";

function getIntensityClass(intensity: number): string {
  switch (intensity) {
    case 0:
      return "bg-gray-800/60";
    case 1:
      return "bg-teal-900/80";
    case 2:
      return "bg-teal-700/80";
    case 3:
      return "bg-teal-500";
    case 4:
      return "bg-teal-400";
    default:
      return "bg-gray-800/60";
  }
}

export function ConsistencyHeatmap({ recent }: { recent: any[] }) {
  const [selectedDateKey, setSelectedDateKey] = useState<string | null>(null);

  const safeRecent = useMemo(() => (Array.isArray(recent) ? recent : []), [recent]);

  const days = useMemo(() => buildHeatmapDays(safeRecent, 30), [safeRecent]);

  const summary30Day = useMemo(() => calculate30DaySummary(safeRecent, 30), [safeRecent]);

  const selectedDayData = useMemo(() => {
    if (!selectedDateKey) return null;
    return calculateDayActivity(safeRecent, selectedDateKey);
  }, [safeRecent, selectedDateKey]);

  const handleCellClick = (dateKey: string) => {
    setSelectedDateKey((prev) => (prev === dateKey ? null : dateKey));
  };

  const handleClearSelection = () => {
    setSelectedDateKey(null);
  };

  const todayKey = toDateKey(new Date());

  return (
    <div className="flex flex-col gap-3">
      <div
        className="grid grid-cols-[repeat(10,minmax(0,1fr))] gap-1.5 sm:gap-2"
        role="grid"
        aria-label="Last 30 days activity heatmap"
      >
        {days.map((day) => {
          const isSelected = selectedDateKey === day.dateKey;
          const sessionText = `${day.attempts} practice session${day.attempts === 1 ? "" : "s"}`;
          const titleText = `${day.displayDate}${day.isToday ? " (Today)" : ""}: ${sessionText}${
            isSelected ? " - Click to deselect" : " - Click to view day activity"
          }`;

          return (
            <button
              key={day.dateKey}
              type="button"
              onClick={() => handleCellClick(day.dateKey)}
              aria-label={titleText}
              aria-pressed={isSelected}
              title={titleText}
              className={`w-full aspect-square rounded-sm ${getIntensityClass(
                day.intensity
              )} transition-all duration-150 cursor-pointer focus:outline-none focus:ring-2 focus:ring-teal-400 relative ${
                isSelected
                  ? "ring-2 ring-teal-400 ring-offset-2 ring-offset-[#111827] shadow-lg shadow-teal-500/30 scale-110 z-10"
                  : "hover:ring-1 hover:ring-teal-300 hover:scale-105"
              }`}
            >
              {day.isToday && (
                <span
                  className="absolute bottom-0.5 right-0.5 w-1 h-1 rounded-full bg-teal-300 opacity-90"
                  title="Today"
                />
              )}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between text-xs text-muted gap-2">
        <span>Past 30 days</span>
        <div className="flex items-center gap-1.5 text-xs">
          <span>Less</span>
          <div className="w-3 h-3 rounded-sm bg-gray-800/60" aria-hidden="true"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-900/80" aria-hidden="true"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-700/80" aria-hidden="true"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-500" aria-hidden="true"></div>
          <div className="w-3 h-3 rounded-sm bg-teal-400" aria-hidden="true"></div>
          <span>More</span>
        </div>
      </div>

      {selectedDayData ? (
        <div
          data-testid="selected-day-activity"
          className="mt-2 p-3.5 rounded-lg bg-surface/50 border border-line flex flex-col gap-3 transition-all duration-200"
        >
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <Calendar size={15} className="text-teal" />
              <span className="text-sm font-semibold text-white">
                Selected Day Activity: <span className="text-teal">{selectedDayData.displayDate}</span>
              </span>
              {selectedDayData.dateKey === todayKey && (
                <span className="text-[10px] uppercase font-bold tracking-wider bg-teal/20 text-teal px-1.5 py-0.5 rounded border border-teal/30">
                  Today
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={handleClearSelection}
              className="text-xs text-muted hover:text-white px-2 py-1 rounded border border-line hover:border-teal/50 bg-paper/60 transition-colors flex items-center gap-1 cursor-pointer"
              title="Clear selection and return to 30-day summary"
            >
              <X size={12} />
              Clear Selection
            </button>
          </div>

          {selectedDayData.attempts > 0 ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                <div className="p-2.5 rounded bg-background/50 border border-line/60">
                  <p className="text-muted">Practice Sessions</p>
                  <p className="text-base font-bold text-white mt-0.5">{selectedDayData.attempts}</p>
                </div>
                <div className="p-2.5 rounded bg-background/50 border border-line/60">
                  <p className="text-muted">Completed Questions</p>
                  <p className="text-base font-bold text-green mt-0.5">{selectedDayData.solved}</p>
                </div>
                <div className="p-2.5 rounded bg-background/50 border border-line/60 col-span-2 sm:col-span-1">
                  <p className="text-muted">Difficulty Solved</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-teal font-medium" title="Easy solved">
                      E: {selectedDayData.easySolved}/{selectedDayData.easyCount}
                    </span>
                    <span className="text-amber font-medium" title="Medium solved">
                      M: {selectedDayData.mediumSolved}/{selectedDayData.mediumCount}
                    </span>
                    <span className="text-red font-medium" title="Hard solved">
                      H: {selectedDayData.hardSolved}/{selectedDayData.hardCount}
                    </span>
                  </div>
                </div>
              </div>

              {selectedDayData.entries.length > 0 && (
                <div className="flex flex-col gap-1.5 mt-0.5">
                  <p className="text-xs font-medium text-muted">Questions practiced on this day:</p>
                  <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto pr-1">
                    {selectedDayData.entries.map((entry, idx) => {
                      const diff = normalizeDifficulty(entry?.difficulty);
                      const isSolved = Boolean(entry?.is_solved);
                      return (
                        <div
                          key={idx}
                          className="flex items-center justify-between gap-2 p-2 rounded bg-background/40 border border-line/50 text-xs"
                        >
                          <div className="flex items-center gap-2 truncate">
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${isSolved ? "bg-green" : "bg-muted"}`}
                            />
                            <span className="truncate text-white font-medium">
                              {entry?.question_title ||
                                entry?.question_id ||
                                `Question #${entry?.qnum || idx + 1}`}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                                diff === "easy"
                                  ? "bg-teal/15 text-teal border border-teal/30"
                                  : diff === "medium"
                                  ? "bg-amber/15 text-amber border border-amber/30"
                                  : diff === "hard"
                                  ? "bg-red/15 text-red border border-red/30"
                                  : "bg-gray-800 text-muted"
                              }`}
                            >
                              {diff}
                            </span>
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                                isSolved ? "text-green bg-green/10" : "text-muted bg-gray-800"
                              }`}
                            >
                              {isSolved ? "Solved" : "Attempted"}
                            </span>
                            {entry?.qnum && (
                              <Link
                                href={`/solve?qnum=${encodeURIComponent(entry.qnum)}`}
                                className="text-teal hover:underline text-[11px] ml-1"
                                title="Practice again"
                              >
                                Solve
                              </Link>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-4 px-2 text-xs text-muted bg-background/30 rounded border border-line/40">
              <p className="text-sm font-medium text-gray-300 mb-1">No practice sessions on this day</p>
              <p>
                Select a highlighted date cell to view session details, or solve a problem today to build your streak!
              </p>
            </div>
          )}
        </div>
      ) : (
        <div
          data-testid="30-day-summary"
          className="mt-2 p-3.5 rounded-lg bg-surface/50 border border-line flex flex-col gap-3 transition-all duration-200"
        >
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <Activity size={15} className="text-teal" />
              <span className="text-sm font-semibold text-white">30-Day Activity Summary</span>
            </div>
            <span className="text-xs text-muted">Click any day above for details</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
            <div className="p-2.5 rounded bg-background/50 border border-line/60">
              <p className="text-muted">Active Days</p>
              <p className="text-base font-bold text-teal mt-0.5">
                {summary30Day.activeDays}{" "}
                <span className="text-xs font-normal text-muted">
                  / 30 ({summary30Day.activePercent}%)
                </span>
              </p>
            </div>
            <div className="p-2.5 rounded bg-background/50 border border-line/60">
              <p className="text-muted">Total Sessions</p>
              <p className="text-base font-bold text-white mt-0.5">{summary30Day.totalSessions}</p>
            </div>
            <div className="p-2.5 rounded bg-background/50 border border-line/60 col-span-2 sm:col-span-1">
              <p className="text-muted">Questions Solved</p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-teal font-medium" title="Easy solved">
                  E: {summary30Day.easySolved}
                </span>
                <span className="text-amber font-medium" title="Medium solved">
                  M: {summary30Day.mediumSolved}
                </span>
                <span className="text-red font-medium" title="Hard solved">
                  H: {summary30Day.hardSolved}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

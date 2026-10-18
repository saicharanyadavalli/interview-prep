/**
 * Streak and Activity Analytics Utilities
 * Provides timezone-safe date normalization, streak calculations, and heatmap aggregation.
 */

/**
 * Returns a "YYYY-MM-DD" string for the given local calendar Date.
 */
export function toDateKey(date: Date): string {
  if (!date || Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Normalizes any date representation (string, timestamp, Date object) into a "YYYY-MM-DD" date key.
 * Prevents timezone-shifting bugs (e.g. UTC midnight strings being pulled to the previous day in west-of-UTC timezones).
 */
export function getEntryDateKey(entry: any): string | null {
  if (!entry) return null;

  // Extract raw date candidate from supported field names
  const raw =
    typeof entry === "object"
      ? entry.updated_at ||
        entry.completed_at ||
        entry.created_at ||
        entry.timestamp ||
        entry.date
      : entry;

  if (!raw) return null;

  if (typeof raw === "string") {
    const trimmed = raw.trim();

    // Direct match for date-only format (e.g., "2026-10-18")
    const dateOnlyMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (dateOnlyMatch) {
      return `${dateOnlyMatch[1]}-${dateOnlyMatch[2]}-${dateOnlyMatch[3]}`;
    }

    // Try parsing standard timestamp
    const parsed = new Date(trimmed);
    if (!Number.isNaN(parsed.getTime())) {
      return toDateKey(parsed);
    }

    // Fallback: extract leading YYYY-MM-DD from non-standard formatted strings
    const prefixMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (prefixMatch) {
      return `${prefixMatch[1]}-${prefixMatch[2]}-${prefixMatch[3]}`;
    }

    return null;
  }

  if (raw instanceof Date) {
    return Number.isNaN(raw.getTime()) ? null : toDateKey(raw);
  }

  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : toDateKey(parsed);
}

/**
 * Timezone-safe formatting of a date key or ISO string into a human-readable display string.
 * Example: "2026-10-18" -> "Oct 18, 2026".
 */
export function formatDateDisplay(input: string | Date | null | undefined): string {
  if (!input) return "Date unavailable";

  if (typeof input === "string") {
    const trimmed = input.trim();
    // Parse pure YYYY-MM-DD directly into local noon to prevent midnight/DST boundary shifts
    const match = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
      const year = parseInt(match[1], 10);
      const month = parseInt(match[2], 10) - 1;
      const day = parseInt(match[3], 10);
      const d = new Date(year, month, day, 12, 0, 0);
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }

    const parsed = new Date(trimmed);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }

    return trimmed;
  }

  if (input instanceof Date) {
    if (Number.isNaN(input.getTime())) return "Date unavailable";
    return input.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  try {
    const parsed = new Date(input);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }
  } catch (_) {}

  return String(input);
}

/**
 * Calculates current consecutive practice streak in days from recent activity entries.
 * Handles edge cases:
 * - Practiced today: streak starts from today and counts backwards consecutive days.
 * - Practiced yesterday (not yet today): streak remains active and counts backwards from yesterday.
 * - Neither today nor yesterday: streak is broken (0).
 * - Deduplicates multiple practices on the same calendar day.
 * - Disregards chronological entry order in input list.
 * - Prevents client-side date mutation side effects.
 */
export function calculateStreak(recent: any[]): number {
  if (!Array.isArray(recent) || recent.length === 0) {
    return 0;
  }

  const uniqueDays = new Set<string>();
  for (const entry of recent) {
    const key = getEntryDateKey(entry);
    if (key) {
      uniqueDays.add(key);
    }
  }

  if (uniqueDays.size === 0) return 0;

  const now = new Date();
  const todayKey = toDateKey(now);

  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0, 0);
  const yesterdayKey = toDateKey(yesterday);

  let startOffset: number;
  if (uniqueDays.has(todayKey)) {
    startOffset = 0;
  } else if (uniqueDays.has(yesterdayKey)) {
    startOffset = 1;
  } else {
    return 0;
  }

  let streak = 0;
  let offset = startOffset;
  while (true) {
    const cursor = new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset, 0, 0, 0, 0);
    const key = toDateKey(cursor);
    if (!uniqueDays.has(key)) {
      break;
    }
    streak += 1;
    offset += 1;
  }

  return streak;
}

export interface DayDifficultyStats {
  easyCount: number;
  easySolved: number;
  mediumCount: number;
  mediumSolved: number;
  hardCount: number;
  hardSolved: number;
}

export interface DayActivityData extends DayDifficultyStats {
  dateKey: string;
  displayDate: string;
  attempts: number;
  solved: number;
  entries: any[];
}

/**
 * Normalizes question difficulty into "easy" | "medium" | "hard" | "unknown".
 */
export function normalizeDifficulty(value: any): "easy" | "medium" | "hard" | "unknown" {
  const text = String(value || "").trim().toLowerCase();
  if (text === "easy" || text === "medium" || text === "hard") {
    return text;
  }
  return "unknown";
}

/**
 * Aggregates activity details for a specific day.
 */
export function calculateDayActivity(recent: any[], targetDateKey: string): DayActivityData {
  const entries: any[] = [];
  let solved = 0;
  let easyCount = 0;
  let easySolved = 0;
  let mediumCount = 0;
  let mediumSolved = 0;
  let hardCount = 0;
  let hardSolved = 0;

  if (Array.isArray(recent) && targetDateKey) {
    for (const entry of recent) {
      const key = getEntryDateKey(entry);
      if (key === targetDateKey) {
        entries.push(entry);
        const isSolved = Boolean(entry?.is_solved);
        if (isSolved) solved += 1;

        const diff = normalizeDifficulty(entry?.difficulty);
        if (diff === "easy") {
          easyCount += 1;
          if (isSolved) easySolved += 1;
        } else if (diff === "medium") {
          mediumCount += 1;
          if (isSolved) mediumSolved += 1;
        } else if (diff === "hard") {
          hardCount += 1;
          if (isSolved) hardSolved += 1;
        }
      }
    }
  }

  return {
    dateKey: targetDateKey,
    displayDate: formatDateDisplay(targetDateKey),
    attempts: entries.length,
    solved,
    easyCount,
    easySolved,
    mediumCount,
    mediumSolved,
    hardCount,
    hardSolved,
    entries,
  };
}

export interface HeatmapDayCell {
  dateKey: string;
  displayDate: string;
  attempts: number;
  intensity: number;
  isToday: boolean;
}

/**
 * Builds the array of days for the consistency heatmap (default 30 days).
 * Returned array goes from oldest day to today.
 */
export function buildHeatmapDays(recent: any[], totalDays: number = 30): HeatmapDayCell[] {
  const countsByDate: Record<string, number> = {};
  if (Array.isArray(recent)) {
    for (const entry of recent) {
      const key = getEntryDateKey(entry);
      if (key) {
        countsByDate[key] = (countsByDate[key] || 0) + 1;
      }
    }
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayKey = toDateKey(today);

  const days: HeatmapDayCell[] = [];
  for (let offset = totalDays - 1; offset >= 0; offset -= 1) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset, 0, 0, 0, 0);
    const key = toDateKey(d);
    const attempts = countsByDate[key] || 0;
    const intensity = Math.min(4, attempts);

    days.push({
      dateKey: key,
      displayDate: formatDateDisplay(key),
      attempts,
      intensity,
      isToday: key === todayKey,
    });
  }

  return days;
}

export interface ThirtyDaySummary {
  totalDays: number;
  activeDays: number;
  activePercent: number;
  totalSessions: number;
  totalSolved: number;
  easySolved: number;
  mediumSolved: number;
  hardSolved: number;
}

/**
 * Calculates aggregate summary over the past N days (default 30).
 */
export function calculate30DaySummary(recent: any[], totalDays: number = 30): ThirtyDaySummary {
  const days = buildHeatmapDays(recent, totalDays);
  const validKeys = new Set(days.map((d) => d.dateKey));

  let activeDays = 0;
  let totalSessions = 0;
  let totalSolved = 0;
  let easySolved = 0;
  let mediumSolved = 0;
  let hardSolved = 0;

  for (const day of days) {
    if (day.attempts > 0) {
      activeDays += 1;
      totalSessions += day.attempts;
    }
  }

  if (Array.isArray(recent)) {
    for (const entry of recent) {
      const key = getEntryDateKey(entry);
      if (key && validKeys.has(key)) {
        const isSolved = Boolean(entry?.is_solved);
        if (isSolved) {
          totalSolved += 1;
          const diff = normalizeDifficulty(entry?.difficulty);
          if (diff === "easy") easySolved += 1;
          else if (diff === "medium") mediumSolved += 1;
          else if (diff === "hard") hardSolved += 1;
        }
      }
    }
  }

  const activePercent = totalDays > 0 ? Math.round((activeDays / totalDays) * 100) : 0;

  return {
    totalDays,
    activeDays,
    activePercent,
    totalSessions,
    totalSolved,
    easySolved,
    mediumSolved,
    hardSolved,
  };
}

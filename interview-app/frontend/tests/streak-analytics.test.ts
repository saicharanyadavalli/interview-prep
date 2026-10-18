import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  toDateKey,
  getEntryDateKey,
  formatDateDisplay,
  calculateStreak,
  calculateDayActivity,
  calculate30DaySummary,
  buildHeatmapDays,
} from "../src/utils/streak-analytics.ts";

describe("Streak and Activity Analytics Utilities (Bug G)", () => {
  describe("toDateKey and getEntryDateKey (Timezone Safety)", () => {
    it("formats local Date into YYYY-MM-DD", () => {
      const d = new Date(2026, 9, 18); // Note: month 9 is October
      assert.equal(toDateKey(d), "2026-10-18");
    });

    it("extracts date key directly from YYYY-MM-DD string without UTC shift", () => {
      assert.equal(getEntryDateKey({ updated_at: "2026-10-18" }), "2026-10-18");
      assert.equal(getEntryDateKey({ date: "2026-05-04" }), "2026-05-04");
    });

    it("supports various entry property names (updated_at, completed_at, created_at, timestamp, date)", () => {
      assert.equal(getEntryDateKey({ completed_at: "2026-10-18" }), "2026-10-18");
      assert.equal(getEntryDateKey({ created_at: "2026-10-18" }), "2026-10-18");
      assert.equal(getEntryDateKey({ timestamp: "2026-10-18" }), "2026-10-18");
      assert.equal(getEntryDateKey({ date: "2026-10-18" }), "2026-10-18");
    });

    it("parses valid ISO string timestamps", () => {
      const key = getEntryDateKey({ updated_at: "2026-10-18T12:00:00.000Z" });
      assert.ok(key && key.startsWith("2026-10-"));
    });

    it("returns null for empty or invalid entries", () => {
      assert.equal(getEntryDateKey(null), null);
      assert.equal(getEntryDateKey({}), null);
      assert.equal(getEntryDateKey({ updated_at: "invalid-date-string" }), null);
    });
  });

  describe("formatDateDisplay", () => {
    it("formats YYYY-MM-DD string into readable date without 1-day timezone rollback", () => {
      const formatted = formatDateDisplay("2026-10-18");
      assert.ok(formatted.includes("Oct"), `Expected month Oct in ${formatted}`);
      assert.ok(formatted.includes("18"), `Expected day 18 in ${formatted}`);
      assert.ok(formatted.includes("2026"), `Expected year 2026 in ${formatted}`);
    });

    it("handles Date objects and fallback strings gracefully", () => {
      assert.equal(formatDateDisplay(null), "Date unavailable");
      assert.equal(formatDateDisplay(""), "Date unavailable");
      const d = new Date(2026, 9, 18);
      const formatted = formatDateDisplay(d);
      assert.ok(formatted.includes("Oct") && formatted.includes("18"));
    });
  });

  describe("calculateStreak edge cases", () => {
    function makeDay(offsetDaysAgo: number): string {
      const d = new Date();
      d.setDate(d.getDate() - offsetDaysAgo);
      return toDateKey(d);
    }

    it("returns 0 for empty or invalid inputs", () => {
      assert.equal(calculateStreak([]), 0);
      assert.equal(calculateStreak(null as any), 0);
      assert.equal(calculateStreak([{} as any]), 0);
    });

    it("returns 1 when user practiced only today", () => {
      const today = makeDay(0);
      const recent = [{ updated_at: today, is_solved: true }];
      assert.equal(calculateStreak(recent), 1);
    });

    it("returns 1 when user practiced yesterday but not yet today (active streak window)", () => {
      const yesterday = makeDay(1);
      const recent = [{ updated_at: yesterday, is_solved: true }];
      assert.equal(calculateStreak(recent), 1);
    });

    it("returns 3 when user practiced today, yesterday, and 2 days ago", () => {
      const recent = [
        { updated_at: makeDay(0), is_solved: true },
        { updated_at: makeDay(1), is_solved: true },
        { updated_at: makeDay(2), is_solved: true },
      ];
      assert.equal(calculateStreak(recent), 3);
    });

    it("returns 2 when user practiced yesterday and 2 days ago, but not yet today", () => {
      const recent = [
        { updated_at: makeDay(1), is_solved: true },
        { updated_at: makeDay(2), is_solved: true },
      ];
      assert.equal(calculateStreak(recent), 2);
    });

    it("returns 0 when user practiced 2 days ago, but neither today nor yesterday (broken streak)", () => {
      const recent = [
        { updated_at: makeDay(2), is_solved: true },
        { updated_at: makeDay(3), is_solved: true },
      ];
      assert.equal(calculateStreak(recent), 0);
    });

    it("deduplicates multiple sessions on the same calendar day", () => {
      const today = makeDay(0);
      const yesterday = makeDay(1);
      const recent = [
        { updated_at: today, is_solved: true },
        { updated_at: today, is_solved: false },
        { updated_at: today, is_solved: true },
        { updated_at: yesterday, is_solved: true },
        { updated_at: yesterday, is_solved: true },
      ];
      assert.equal(calculateStreak(recent), 2);
    });

    it("handles out-of-order recent entries robustly", () => {
      const recent = [
        { updated_at: makeDay(2), is_solved: true },
        { updated_at: makeDay(0), is_solved: true },
        { updated_at: makeDay(1), is_solved: true },
      ];
      assert.equal(calculateStreak(recent), 3);
    });
  });

  describe("calculateDayActivity and calculate30DaySummary", () => {
    it("aggregates day activity including difficulty breakdown and solved count", () => {
      const targetDate = "2026-10-18";
      const recent = [
        { updated_at: targetDate, question_title: "Two Sum", difficulty: "Easy", is_solved: true },
        { updated_at: targetDate, question_title: "LRU Cache", difficulty: "Medium", is_solved: false },
        { updated_at: targetDate, question_title: "Trapping Rain Water", difficulty: "Hard", is_solved: true },
        { updated_at: "2026-10-17", question_title: "Merge Intervals", difficulty: "Medium", is_solved: true },
      ];

      const activity = calculateDayActivity(recent, targetDate);
      assert.equal(activity.dateKey, targetDate);
      assert.equal(activity.attempts, 3);
      assert.equal(activity.solved, 2);
      assert.equal(activity.easyCount, 1);
      assert.equal(activity.easySolved, 1);
      assert.equal(activity.mediumCount, 1);
      assert.equal(activity.mediumSolved, 0);
      assert.equal(activity.hardCount, 1);
      assert.equal(activity.hardSolved, 1);
      assert.equal(activity.entries.length, 3);
    });

    it("returns zero counts gracefully for a day with no activity", () => {
      const activity = calculateDayActivity([], "2026-10-18");
      assert.equal(activity.attempts, 0);
      assert.equal(activity.solved, 0);
      assert.equal(activity.entries.length, 0);
    });

    it("calculates 30-day summary metrics properly", () => {
      const today = toDateKey(new Date());
      const yesterday = toDateKey(new Date(Date.now() - 86400000));
      const recent = [
        { updated_at: today, difficulty: "Easy", is_solved: true },
        { updated_at: today, difficulty: "Medium", is_solved: true },
        { updated_at: yesterday, difficulty: "Hard", is_solved: false },
      ];

      const summary = calculate30DaySummary(recent, 30);
      assert.equal(summary.totalDays, 30);
      assert.equal(summary.activeDays, 2);
      assert.equal(summary.totalSessions, 3);
      assert.equal(summary.totalSolved, 2);
      assert.equal(summary.easySolved, 1);
      assert.equal(summary.mediumSolved, 1);
      assert.equal(summary.hardSolved, 0);
    });

    it("builds 30 heatmap day cells ending at today", () => {
      const days = buildHeatmapDays([], 30);
      assert.equal(days.length, 30);
      const todayKey = toDateKey(new Date());
      assert.equal(days[days.length - 1].dateKey, todayKey);
      assert.equal(days[days.length - 1].isToday, true);
    });
  });
});

/**
 * Navigation routes and query utilities for Dashboard, Sidebar, and Question navigation.
 */

export const DASHBOARD_NAV_ROUTES = {
  BRAND_HOME: "/dashboard",
  LANDING_HOME: "/",
  TOTAL_ATTEMPTED: "/questions",
  SOLVED: "/questions?status=solved",
  REVISIT_QUEUE: "/revisit",
  STREAKS: "/progress",
} as const;

export type SupportedStatusFilter = "solved" | "unsolved" | "attempted";

export interface ParsedStatusFilter {
  field: "status";
  operator: "is";
  value: SupportedStatusFilter;
}

export type SearchParamsSource =
  | URLSearchParams
  | { get: (key: string) => string | null }
  | Record<string, string | number | boolean | null | undefined>;

/**
 * Extracts and normalizes the status filter parameter from search params.
 * Supports URLSearchParams, ReadonlyURLSearchParams (Next.js), or plain object/record.
 */
export function parseStatusFilterFromParams(
  searchParams?: SearchParamsSource | null
): ParsedStatusFilter | null {
  if (!searchParams) return null;

  let rawValue: string | null = null;
  if ("get" in searchParams && typeof searchParams.get === "function") {
    rawValue = searchParams.get("status");
  } else if (typeof searchParams === "object" && "status" in searchParams) {
    const val = searchParams.status;
    rawValue = val !== null && val !== undefined ? String(val) : null;
  }

  if (!rawValue) return null;

  const normalized = rawValue.trim().toLowerCase();
  if (normalized === "solved") {
    return { field: "status", operator: "is", value: "solved" };
  }
  if (normalized === "unsolved" || normalized === "not_solved" || normalized === "notsolved") {
    return { field: "status", operator: "is", value: "unsolved" };
  }
  if (normalized === "attempted") {
    return { field: "status", operator: "is", value: "attempted" };
  }

  return null;
}

/**
 * Builds the questions page URL given an optional status filter.
 */
export function buildQuestionsUrlWithFilter(status?: SupportedStatusFilter | string | null): string {
  if (!status) return "/questions";
  const norm = status.trim().toLowerCase();
  if (norm === "solved" || norm === "unsolved" || norm === "attempted") {
    return `/questions?status=${encodeURIComponent(norm)}`;
  }
  return "/questions";
}

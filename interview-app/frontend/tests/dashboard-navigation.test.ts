import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  DASHBOARD_NAV_ROUTES,
  parseStatusFilterFromParams,
  buildQuestionsUrlWithFilter,
} from "../src/utils/dashboard-navigation.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, "..");

describe("Bug F: Application Logo Navigation", () => {
  it("defines DASHBOARD_NAV_ROUTES.BRAND_HOME pointing to /dashboard", () => {
    assert.equal(DASHBOARD_NAV_ROUTES.BRAND_HOME, "/dashboard");
  });

  it("ensures Sidebar.tsx wraps brand logo and title in a semantic Link to /dashboard", () => {
    const sidebarPath = path.join(frontendDir, "src", "components", "Sidebar.tsx");
    const content = fs.readFileSync(sidebarPath, "utf-8");

    // Must have Link with href="/dashboard" and className="sidebar-brand-link"
    assert.match(
      content,
      /<Link[^>]*href=["']\/dashboard["'][^>]*className=["'][^"']*sidebar-brand-link[^"']*["']/,
      "Sidebar brand must be a Next.js Link pointing to /dashboard with sidebar-brand-link class"
    );

    // Must have aria-label and title for accessibility
    assert.match(content, /aria-label=["']Interview Assistant Dashboard["']/);
    assert.match(content, /title=["'][^"']*Dashboard["']/);

    // Must wrap brand logo and text
    assert.match(
      content,
      /<Link[^>]*>[\s\S]*?<Image[^>]*brand-logo[\s\S]*?sidebar-brand-text[\s\S]*?<\/Link>/,
      "Sidebar Link must wrap both the brand-logo Image and sidebar-brand-text"
    );

    // Must close mobile menu on click
    assert.match(content, /onClick=\{closeMobile\}/);
  });

  it("ensures questions page header brand logo links to /dashboard", () => {
    const questionsPath = path.join(frontendDir, "src", "app", "questions", "page.tsx");
    const content = fs.readFileSync(questionsPath, "utf-8");

    assert.match(
      content,
      /<Link[^>]*href=["']\/dashboard["'][^>]*>[\s\S]*?<Image[^>]*brand-logo[\s\S]*?Interview Assistant[\s\S]*?<\/Link>/,
      "Questions page header must wrap brand logo and title in Link to /dashboard"
    );
  });

  it("ensures leetcode DSA page header brand logo links to /dashboard", () => {
    const leetcodePath = path.join(frontendDir, "src", "app", "dsa", "leetcode", "page.tsx");
    const content = fs.readFileSync(leetcodePath, "utf-8");

    assert.match(
      content,
      /<Link[^>]*href=["']\/dashboard["'][^>]*>[\s\S]*?<Image[^>]*brand-logo[\s\S]*?Interview Assistant[\s\S]*?<\/Link>/,
      "LeetCode DSA page header must wrap brand logo and title in Link to /dashboard"
    );
  });

  it("ensures landing page (page.tsx) brand logos navigate appropriately", () => {
    const landingPath = path.join(frontendDir, "src", "app", "page.tsx");
    const content = fs.readFileSync(landingPath, "utf-8");

    // Header logo should navigate to /dashboard (if authenticated) or /
    assert.match(
      content,
      /<Link[^>]*href=\{user \? ["']\/dashboard["'] : ["']\/["']\}[\s\S]*?logo-mark\.svg[\s\S]*?Interview Assistant[\s\S]*?<\/Link>/,
      "Landing page navbar logo must link to dashboard or home"
    );
  });

  it("ensures globals.css defines accessible styles for .sidebar-brand-link", () => {
    const cssPath = path.join(frontendDir, "src", "app", "globals.css");
    const content = fs.readFileSync(cssPath, "utf-8");

    assert.ok(content.includes(".sidebar-brand-link"), "globals.css must define .sidebar-brand-link");
    assert.ok(content.includes(".sidebar-brand-link:hover"), "globals.css must define hover styles for brand link");
    assert.ok(content.includes(".sidebar-brand-link:focus-visible"), "globals.css must define focus-visible styles for keyboard accessibility");
    assert.ok(content.includes('html[data-sidebar="collapsed"] .sidebar-brand-link'), "globals.css must support collapsed sidebar brand link");
  });
});

describe("Bug L: Dashboard Stat Cards & Query Parameter Navigation", () => {
  it("defines DASHBOARD_NAV_ROUTES for stat cards correctly", () => {
    assert.equal(DASHBOARD_NAV_ROUTES.TOTAL_ATTEMPTED, "/questions");
    assert.equal(DASHBOARD_NAV_ROUTES.SOLVED, "/questions?status=solved");
    assert.equal(DASHBOARD_NAV_ROUTES.REVISIT_QUEUE, "/revisit");
    assert.equal(DASHBOARD_NAV_ROUTES.STREAKS, "/progress");
  });

  it("ensures dashboard/page.tsx #statsGrid links match navigation requirements", () => {
    const dashboardPath = path.join(frontendDir, "src", "app", "dashboard", "page.tsx");
    const content = fs.readFileSync(dashboardPath, "utf-8");

    // Total Attempted card links to /questions
    assert.match(
      content,
      /<Link[^>]*href=["']\/questions["'][^>]*className=["'][^"']*stat-card attempted[^"']*["']/,
      "Total Attempted stat card must link to /questions"
    );

    // Solved card links to /questions?status=solved
    assert.match(
      content,
      /<Link[^>]*href=["']\/questions\?status=solved["'][^>]*className=["'][^"']*stat-card solved[^"']*["']/,
      "Solved stat card must link to /questions?status=solved"
    );

    // Revisit Queue card links to /revisit
    assert.match(
      content,
      /<Link[^>]*href=["']\/revisit["'][^>]*className=["'][^"']*stat-card revisit[^"']*["']/,
      "Revisit Queue stat card must link to /revisit"
    );

    // Streaks card links to /progress
    assert.match(
      content,
      /<Link[^>]*href=["']\/progress["'][^>]*className=["'][^"']*stat-card streak[^"']*["']/,
      "Streaks stat card must link to /progress"
    );
  });

  it("ensures dashboard/page.tsx Recently Attempted section has navigable header without nested link conflicts", () => {
    const dashboardPath = path.join(frontendDir, "src", "app", "dashboard", "page.tsx");
    const content = fs.readFileSync(dashboardPath, "utf-8");

    // Section header links to /questions
    assert.match(
      content,
      /<Link[^>]*href=["']\/questions["'][^>]*className=["'][^"']*section-title-link[^"']*["'][\s\S]*?Recently Attempted[\s\S]*?<\/Link>/,
      "Recently Attempted header must link to /questions"
    );

    // Track items do NOT wrap the entire item in <a> when it contains child links
    // Each track item should be a div containing independent links (e.g. track-title-link and Practice button)
    assert.match(
      content,
      /<div key=\{i\} className=["']track-item["']>[\s\S]*?<Link[^>]*track-title-link[\s\S]*?<Link[^>]*className=["']btn btn-sm["']/,
      "Track item must have independent title link and Practice button without nested <a> tags"
    );
  });

  it("ensures globals.css defines hover and active states for stat-card links", () => {
    const cssPath = path.join(frontendDir, "src", "app", "globals.css");
    const content = fs.readFileSync(cssPath, "utf-8");

    assert.ok(content.includes("a.stat-card:hover"), "globals.css must have a.stat-card:hover");
    assert.ok(content.includes("a.stat-card:active"), "globals.css must have a.stat-card:active");
    assert.ok(content.includes("a.stat-card:focus-visible"), "globals.css must have a.stat-card:focus-visible");
  });
});

describe("Status Query Parameter Parsing (Questions Page)", () => {
  it("parses ?status=solved from URLSearchParams", () => {
    const params = new URLSearchParams("status=solved");
    const result = parseStatusFilterFromParams(params);
    assert.deepEqual(result, {
      field: "status",
      operator: "is",
      value: "solved",
    });
  });

  it("parses ?status=solved case-insensitively and trims whitespace", () => {
    const params = new URLSearchParams("status=%20SOLVED%20");
    const result = parseStatusFilterFromParams(params);
    assert.deepEqual(result, {
      field: "status",
      operator: "is",
      value: "solved",
    });
  });

  it("parses ?status=unsolved and variants", () => {
    assert.deepEqual(parseStatusFilterFromParams(new URLSearchParams("status=unsolved")), {
      field: "status",
      operator: "is",
      value: "unsolved",
    });
    assert.deepEqual(parseStatusFilterFromParams(new URLSearchParams("status=not_solved")), {
      field: "status",
      operator: "is",
      value: "unsolved",
    });
  });

  it("parses ?status=attempted", () => {
    const params = new URLSearchParams("status=attempted");
    const result = parseStatusFilterFromParams(params);
    assert.deepEqual(result, {
      field: "status",
      operator: "is",
      value: "attempted",
    });
  });

  it("parses status from plain object records or mock Next.js searchParams", () => {
    const mockNextParams = {
      get: (key: string) => (key === "status" ? "solved" : null),
    };
    assert.deepEqual(parseStatusFilterFromParams(mockNextParams), {
      field: "status",
      operator: "is",
      value: "solved",
    });

    const plainObj = { status: "solved", other: "123" };
    assert.deepEqual(parseStatusFilterFromParams(plainObj), {
      field: "status",
      operator: "is",
      value: "solved",
    });
  });

  it("returns null when status param is absent, empty, or unrecognized", () => {
    assert.equal(parseStatusFilterFromParams(new URLSearchParams("")), null);
    assert.equal(parseStatusFilterFromParams(new URLSearchParams("company=Google")), null);
    assert.equal(parseStatusFilterFromParams(new URLSearchParams("status=unknown_value")), null);
    assert.equal(parseStatusFilterFromParams(null), null);
    assert.equal(parseStatusFilterFromParams(undefined), null);
  });

  it("buildQuestionsUrlWithFilter creates correct query strings", () => {
    assert.equal(buildQuestionsUrlWithFilter("solved"), "/questions?status=solved");
    assert.equal(buildQuestionsUrlWithFilter("unsolved"), "/questions?status=unsolved");
    assert.equal(buildQuestionsUrlWithFilter("attempted"), "/questions?status=attempted");
    assert.equal(buildQuestionsUrlWithFilter(null), "/questions");
    assert.equal(buildQuestionsUrlWithFilter(undefined), "/questions");
    assert.equal(buildQuestionsUrlWithFilter(""), "/questions");
    assert.equal(buildQuestionsUrlWithFilter("invalid"), "/questions");
  });

  it("ensures questions/page.tsx utilizes useSearchParams and Suspense", () => {
    const questionsPath = path.join(frontendDir, "src", "app", "questions", "page.tsx");
    const content = fs.readFileSync(questionsPath, "utf-8");

    // Must import useSearchParams
    assert.match(content, /useSearchParams/);

    // Must import parseStatusFilterFromParams
    assert.match(content, /parseStatusFilterFromParams/);

    // Must wrap page in Suspense
    assert.match(content, /<Suspense[\s\S]*?<QuestionsContent \/>[\s\S]*?<\/Suspense>/);

    // Must pass initialFilters to FilterBuilder
    assert.match(content, /initialFilters=\{initialStatusFilter \? \[initialStatusFilter\] : undefined\}/);
  });
});

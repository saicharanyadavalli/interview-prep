import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

describe("Bug K & Bug H Verification: Themes, Sidebar & Accessibility Specialist", () => {
  const frontendDir = path.resolve(__dirname, "..");
  const globalsCssPath = path.join(frontendDir, "src", "app", "globals.css");
  const layoutPath = path.join(frontendDir, "src", "app", "layout.tsx");
  const sidebarPath = path.join(frontendDir, "src", "components", "Sidebar.tsx");
  const cardPath = path.join(frontendDir, "src", "components", "ui", "Card.tsx");
  const badgePath = path.join(frontendDir, "src", "components", "ui", "Badge.tsx");
  const buttonPath = path.join(frontendDir, "src", "components", "ui", "Button.tsx");
  const inputPath = path.join(frontendDir, "src", "components", "ui", "Input.tsx");
  const drawerPath = path.join(frontendDir, "src", "components", "ui", "Drawer.tsx");
  const questionTablePath = path.join(frontendDir, "src", "components", "questions", "QuestionTable.tsx");
  const leetCodeRendererPath = path.join(frontendDir, "src", "components", "LeetCodeRenderer.tsx");

  describe("Bug K: Desktop Sidebar Collapse Button & Mobile Toggle Visibility", () => {
    it("should ensure .sidebar does NOT have overflow-x: hidden which clips the collapse button", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      // Match the .sidebar block
      const sidebarBlockMatch = css.match(/\.sidebar\s*\{([^}]+)\}/);
      assert.ok(sidebarBlockMatch, ".sidebar block must exist in globals.css");
      const block = sidebarBlockMatch[1];
      assert.doesNotMatch(block, /overflow-x\s*:\s*hidden/, ".sidebar must NOT contain overflow-x: hidden");
      assert.match(block, /overflow-x\s*:\s*visible/, ".sidebar must have overflow-x: visible");
    });

    it("should keep overflow-y: auto and overflow-x: hidden on .sidebar-nav", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      const navMatch = css.match(/(?:^|\n)\.sidebar-nav\s*\{([^}]+)\}/);
      assert.ok(navMatch, ".sidebar-nav block must exist in globals.css");
      const block = navMatch[1];
      assert.match(block, /overflow-y\s*:\s*auto/, ".sidebar-nav must have overflow-y: auto");
      assert.match(block, /overflow-x\s*:\s*hidden/, ".sidebar-nav must have overflow-x: hidden");
    });

    it("should style .sidebar-collapse-btn with background var(--paper) and border 1px solid var(--line)", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      const btnMatch = css.match(/\.sidebar-collapse-btn\s*\{([^}]+)\}/);
      assert.ok(btnMatch, ".sidebar-collapse-btn block must exist");
      const block = btnMatch[1];
      assert.match(block, /background\s*:\s*var\(--paper\)/, "Must use var(--paper) background");
      assert.match(block, /border\s*:\s*1px solid var\(--line\)/, "Must use var(--line) border");
      assert.match(block, /box-shadow/, "Must have box-shadow for contrast");
    });

    it("should have clear hover and focus-visible states for .sidebar-collapse-btn", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      assert.match(css, /\.sidebar-collapse-btn:hover\s*\{[^}]*color\s*:\s*var\(--teal\)/);
      assert.match(css, /\.sidebar-collapse-btn:focus-visible\s*\{[^}]*outline/, "Must have focus-visible outline");
    });

    it("should style mobile .sidebar-toggle with accessible touch target (min 44x44px) and z-index 250", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      const toggleMatch = css.match(/\.sidebar-toggle\s*\{([^}]+)\}/);
      assert.ok(toggleMatch, ".sidebar-toggle block must exist");
      const block = toggleMatch[1];
      assert.match(block, /z-index\s*:\s*250/, "Must have z-index 250");
      assert.match(block, /min-width\s*:\s*44px/, "Must have min-width: 44px");
      assert.match(block, /min-height\s*:\s*44px/, "Must have min-height: 44px");
      assert.match(block, /background\s*:\s*var\(--paper\)/, "Must have var(--paper) background");
      assert.match(block, /border\s*:\s*1px solid var\(--line\)/, "Must have var(--line) border");
      assert.match(block, /color\s*:\s*var\(--ink\)/, "Must have var(--ink) text color");
    });

    it("should configure aria-label and aria-expanded on Sidebar buttons", () => {
      const code = fs.readFileSync(sidebarPath, "utf-8");
      assert.match(code, /className="sidebar-toggle"[^>]*aria-label=\{isOpen \? "Close navigation menu" : "Open navigation menu"\}/);
      assert.match(code, /aria-expanded=\{isOpen\}/);
      assert.match(code, /className="sidebar-collapse-btn"[^>]*aria-label=\{isCollapsed \? "Expand sidebar" : "Collapse sidebar"\}/);
      assert.match(code, /aria-expanded=\{!isCollapsed\}/);
    });
  });

  describe("Bug H: Dark Mode and Light Mode Theme Consistency & Elimination of Hydration Flash", () => {
    it("should define gradient variables in both light and dark themes in globals.css", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      assert.match(css, /--bg-gradient-start\s*:\s*#fffbf0/);
      assert.match(css, /--bg-gradient-mid\s*:\s*var\(--bg\)/);
      assert.match(css, /--bg-gradient-end\s*:\s*#f1efe8/);

      assert.match(css, /--bg-gradient-start\s*:\s*#1e293b/);
      assert.match(css, /--bg-gradient-mid\s*:\s*#0f172a/);
      assert.match(css, /--bg-gradient-end\s*:\s*#020617/);
    });

    it("should drive body background using gradient variables", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      assert.match(css, /body\s*\{[^}]*background\s*:\s*radial-gradient\(circle at 10% 10%,\s*var\(--bg-gradient-start\)/);
    });

    it("should NOT have hardcoded data-theme='dark' on <body> in layout.tsx", () => {
      const layout = fs.readFileSync(layoutPath, "utf-8");
      assert.doesNotMatch(layout, /<body[^>]*data-theme="dark"/, "<body> must not hardcode data-theme='dark'");
    });

    it("should inject an inline blocking script in <head> to read localStorage.getItem('theme') before render", () => {
      const layout = fs.readFileSync(layoutPath, "utf-8");
      assert.match(layout, /<head>/);
      assert.match(layout, /localStorage\.getItem\("theme"\)/);
      assert.match(layout, /document\.documentElement\.setAttribute\("data-theme"/);
    });

    it("should read theme cookie in RootLayout for SSR theme awareness", () => {
      const layout = fs.readFileSync(layoutPath, "utf-8");
      assert.match(layout, /cookieStore\.get\("theme"\)/);
      assert.match(layout, /<html[^>]*data-theme=\{initialTheme\}/);
    });

    it("should update cookie and localStorage in Sidebar toggleTheme", () => {
      const sidebar = fs.readFileSync(sidebarPath, "utf-8");
      assert.match(sidebar, /localStorage\.setItem\("theme",\s*next\)/);
      assert.match(sidebar, /document\.documentElement\.setAttribute\("data-theme",\s*next\)/);
      assert.match(sidebar, /document\.cookie\s*=\s*`theme=\$\{next\};/);
    });

    it("should ensure .password-criteria-checklist uses var(--surface-soft) instead of hardcoded dark blue", () => {
      const css = fs.readFileSync(globalsCssPath, "utf-8");
      const match = css.match(/\.password-criteria-checklist\s*\{([^}]+)\}/);
      assert.ok(match, ".password-criteria-checklist must exist");
      assert.doesNotMatch(match[1], /rgba\(15,\s*23,\s*42/, "Must not contain hardcoded dark blue background");
      assert.match(match[1], /background\s*:\s*var\(--surface-soft\)/);
    });
  });

  describe("High-Contrast UI Components Verification", () => {
    it("should verify Card component uses theme variables (bg-paper, border-line, text-ink)", () => {
      const card = fs.readFileSync(cardPath, "utf-8");
      assert.match(card, /bg-paper/);
      assert.match(card, /border-line/);
      assert.match(card, /text-ink/);
      assert.doesNotMatch(card, /bg-zinc-900\/70/);
    });

    it("should verify Badge component has high-contrast colors in light mode", () => {
      const badge = fs.readFileSync(badgePath, "utf-8");
      assert.match(badge, /text-emerald-700/);
      assert.match(badge, /text-amber-700/);
      assert.match(badge, /text-rose-700/);
    });

    it("should verify Button component uses theme tokens", () => {
      const btn = fs.readFileSync(buttonPath, "utf-8");
      assert.match(btn, /bg-surface-chip/);
      assert.match(btn, /border-line/);
      assert.match(btn, /text-ink/);
    });

    it("should verify Input component uses theme tokens", () => {
      const input = fs.readFileSync(inputPath, "utf-8");
      assert.match(input, /bg-paper/);
      assert.match(input, /text-ink/);
      assert.doesNotMatch(input, /bg-zinc-900\/80/);
    });

    it("should verify Drawer component uses bg-paper and border-line", () => {
      const drawer = fs.readFileSync(drawerPath, "utf-8");
      assert.match(drawer, /bg-paper/);
      assert.match(drawer, /border-line/);
      assert.match(drawer, /text-ink/);
      assert.doesNotMatch(drawer, /bg-zinc-900/);
    });

    it("should verify QuestionTable component uses theme tokens", () => {
      const table = fs.readFileSync(questionTablePath, "utf-8");
      assert.match(table, /bg-paper/);
      assert.match(table, /border-line/);
      assert.match(table, /text-ink/);
      assert.doesNotMatch(table, /bg-zinc-900\/60/);
    });

    it("should verify LeetCodeRenderer uses text-ink and does NOT enforce prose-invert in light mode", () => {
      const renderer = fs.readFileSync(leetCodeRendererPath, "utf-8");
      assert.match(renderer, /text-ink/);
      assert.doesNotMatch(renderer, /prose-invert/);
    });
  });
});

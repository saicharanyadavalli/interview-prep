const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const outputDir = path.join(__dirname, '../test-results');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

(async () => {
  console.log("Launching Chromium browser...");
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  console.log("1. Navigating to LeetCode Explorer Page (http://localhost:3000/dsa/leetcode)...");
  await page.goto("http://localhost:3000/dsa/leetcode", { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(outputDir, "leetcode_explorer.png") });
  console.log("  Saved: leetcode_explorer.png");

  console.log("2. Navigating to Problem #1 (http://localhost:3000/dsa/leetcode/1)...");
  await page.goto("http://localhost:3000/dsa/leetcode/1", { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(outputDir, "leetcode_problem_description.png") });
  console.log("  Saved: leetcode_problem_description.png");

  console.log("3. Clicking Solution Approach Accordion Dropdown...");
  await page.click('button:has-text("Solution Approach")');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(outputDir, "leetcode_solution_accordion.png") });
  console.log("  Saved: leetcode_solution_accordion.png");

  console.log("4. Clicking Multi-Language Code Implementation Dropdown...");
  await page.click('button:has-text("Multi-Language Code")');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(outputDir, "leetcode_code_dropdown.png") });
  console.log("  Saved: leetcode_code_dropdown.png");

  await browser.close();
  console.log("\n✅ Playwright E2E Screenshots Completed Successfully!");
})();

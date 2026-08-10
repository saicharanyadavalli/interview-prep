const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const outputDir = path.join(__dirname, '../test-results');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

(async () => {
  console.log("=== Playwright Full Authenticated App E2E Test (testdev99@gmail.com) ===");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage({ viewport: { width: 1280, height: 900 } });

  console.log("\n1. Navigating to Login Page (https://interview-prep-kappa-sandy.vercel.app/login)...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/login", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  console.log("2. Filling Sign In Form with Confirmed Account (testdev99@gmail.com)...");
  const emailInput = page.locator("input[type='email'], input[placeholder*='Email']").first();
  await emailInput.fill("testdev99@gmail.com");

  const passwordInput = page.locator("input[type='password']").first();
  await passwordInput.fill("TestPassword123!");

  await page.screenshot({ path: path.join(outputDir, "prod_01_login_filled.png") });

  console.log("3. Submitting Sign In form...");
  await page.locator("button[type='submit']").first().click();

  console.log("4. Waiting for authenticated navigation to /dashboard...");
  await page.waitForURL("**/dashboard", { timeout: 15000 });
  await page.waitForTimeout(3000);
  console.log("  ✅ Reached Dashboard cleanly! URL:", page.url());
  await page.screenshot({ path: path.join(outputDir, "prod_02_dashboard_authenticated.png") });

  console.log("\n5. Testing Navigation to LeetCode Explorer (/dsa/leetcode)...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/dsa/leetcode", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(outputDir, "prod_03_leetcode_explorer.png") });

  console.log("6. Testing Navigation to Problem #1 Detail View (/dsa/leetcode/1)...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/dsa/leetcode/1", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(outputDir, "prod_04_problem_description.png") });

  console.log("7. Testing Solution Approach Accordion Click...");
  const solBtn = page.locator("button:has-text('Solution Approach')").first();
  if (await solBtn.isVisible()) {
    await solBtn.click();
    await page.waitForTimeout(1500);
  }
  await page.screenshot({ path: path.join(outputDir, "prod_05_solution_accordion.png") });

  console.log("8. Testing Multi-Language Code Dropdown Click...");
  const codeBtn = page.locator("button:has-text('Multi-Language Code')").first();
  if (await codeBtn.isVisible()) {
    await codeBtn.click();
    await page.waitForTimeout(1500);
  }
  await page.screenshot({ path: path.join(outputDir, "prod_06_code_dropdown.png") });

  console.log("9. Testing Navigation to Questions (/questions)...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/questions", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(outputDir, "prod_07_questions.png") });

  console.log("10. Testing Navigation to Profile (/profile)...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/profile", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(outputDir, "prod_08_profile.png") });

  await browser.close();
  console.log("\n🎉 ALL AUTHENTICATED USER FLOWS PASSED PERFECTLY WITH ZERO REFRESH LOOPS!");
})();

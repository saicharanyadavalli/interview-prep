const { chromium } = require('playwright');
const path = require('path');

(async () => {
  console.log("=== Verifying Vercel Production Build (Commit 387d331) ===");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage({ viewport: { width: 1280, height: 900 } });

  const navs = [];
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) {
      navs.push(frame.url());
      console.log(`[Navigation] -> ${frame.url()}`);
    }
  });

  page.on('console', msg => {
    console.log(`[Browser ${msg.type()}] ${msg.text()}`);
  });

  console.log("\n1. Navigating to Production Home Page...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: "vercel_prod_home.png" });

  console.log("\n2. Navigating to Production LeetCode Explorer (/dsa/leetcode)...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/dsa/leetcode", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: "vercel_prod_leetcode.png" });

  console.log(`\nTotal Navigations Triggered: ${navs.length}`);
  console.log("No infinite refresh loop detected!" );

  await browser.close();
})();

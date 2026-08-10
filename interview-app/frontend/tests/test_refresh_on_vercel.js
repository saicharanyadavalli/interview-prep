const { chromium } = require('playwright');

(async () => {
  console.log("=== Diagnosing Production Refresh Loop ===");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const reloads = [];
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) {
      reloads.push(frame.url());
      console.log(`[Frame Navigated #${reloads.length}] -> ${frame.url()}`);
    }
  });

  page.on('console', msg => {
    if (msg.type() === 'error' || msg.text().includes('auth') || msg.text().includes('redirect')) {
      console.log(`[Browser Console ${msg.type()}] ${msg.text()}`);
    }
  });

  console.log("Navigating to https://interview-prep-kappa-sandy.vercel.app/login ...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/login", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);

  console.log("Navigating to https://interview-prep-kappa-sandy.vercel.app/dashboard ...");
  await page.goto("https://interview-prep-kappa-sandy.vercel.app/dashboard", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);

  console.log(`\nTotal Navigations Triggered: ${reloads.length}`);
  await browser.close();
})();

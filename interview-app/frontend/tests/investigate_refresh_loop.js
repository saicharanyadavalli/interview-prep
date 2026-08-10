const { chromium } = require('playwright');

(async () => {
  console.log("=== Playwright Refresh Loop Investigation ===");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const navHistory = [];
  const consoleLogs = [];

  page.on('console', msg => {
    const text = msg.text();
    consoleLogs.push(`[Console ${msg.type()}] ${text}`);
    console.log(`[Console ${msg.type()}] ${text}`);
  });

  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) {
      const url = frame.url();
      navHistory.push({ time: Date.now(), url });
      console.log(`[Navigation Event] Page navigated to: ${url}`);
    }
  });

  page.on('response', resp => {
    if (resp.status() >= 300 && resp.status() < 400) {
      console.log(`[HTTP Redirect ${resp.status()}] ${resp.url()} -> ${resp.headers()['location']}`);
    }
  });

  console.log("\n1. Navigating to https://interview-prep-kappa-sandy.vercel.app/ ...");
  try {
    await page.goto("https://interview-prep-kappa-sandy.vercel.app/", { waitUntil: "domcontentloaded", timeout: 15000 });
    
    // Wait for 10 seconds to observe any infinite refresh loop
    console.log("\n2. Observing page behavior for 10 seconds...");
    await page.waitForTimeout(10000);
  } catch (err) {
    console.log("Error during navigation/observation:", err.message);
  }

  console.log("\n=== Navigation Event Count ===", navHistory.length);
  navHistory.forEach((item, index) => {
    console.log(`  #${index + 1}: ${item.url}`);
  });

  await page.screenshot({ path: "refresh_investigation_landing.png" });

  await browser.close();
})();

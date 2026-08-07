import { test, expect } from '@playwright/test';

const pages = [
  '/',
  '/login',
  '/dashboard',
  '/courses/sql-basics/intro',
  '/practice',
  '/profile'
];
const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'mobile', width: 375, height: 667 },
];

test.describe('Visual & Responsive Audit', () => {
  for (const pagePath of pages) {
    for (const vp of viewports) {
      test(`Visual check: ${pagePath} on ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        try {
          await page.goto(`http://127.0.0.1:3000${pagePath}`);
          await page.waitForTimeout(1000); // wait for rendering
          const safeName = pagePath.replace(/\//g, '_') || '_home';
          await page.screenshot({ path: `../audit/visual/${safeName}_${vp.name}.png`, fullPage: true });
        } catch(e) {
          console.error(`Failed to load ${pagePath}`);
        }
      });
    }
  }
});

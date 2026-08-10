import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(r"C:\Users\yadav\Desktop\learning\gfg crawler\interview-app\frontend\test-results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_e2e_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        print("1. Navigating to LeetCode Explorer Page...")
        page.goto("http://localhost:3000/dsa/leetcode", wait_until="networkidle")
        time.sleep(2)
        page.screenshot(path=str(OUTPUT_DIR / "leetcode_explorer.png"))
        print(f"  Screenshot saved: {OUTPUT_DIR / 'leetcode_explorer.png'}")

        print("2. Navigating to Problem #1 (Two Sum)...")
        page.goto("http://localhost:3000/dsa/leetcode/1", wait_until="networkidle")
        time.sleep(2)
        page.screenshot(path=str(OUTPUT_DIR / "leetcode_problem_description.png"))
        print(f"  Screenshot saved: {OUTPUT_DIR / 'leetcode_problem_description.png'}")

        print("3. Clicking Solution Approach Dropdown...")
        # Click Solution Approach accordion button
        page.click("text=Solution Approach & Complexity Analysis")
        time.sleep(1)
        page.screenshot(path=str(OUTPUT_DIR / "leetcode_solution_accordion.png"))
        print(f"  Screenshot saved: {OUTPUT_DIR / 'leetcode_solution_accordion.png'}")

        print("4. Clicking Multi-Language Code Implementation Dropdown...")
        # Click Code Implementation accordion button
        page.click("text=Multi-Language Code Implementation")
        time.sleep(1)
        page.screenshot(path=str(OUTPUT_DIR / "leetcode_code_dropdown.png"))
        print(f"  Screenshot saved: {OUTPUT_DIR / 'leetcode_code_dropdown.png'}")

        browser.close()
        print("\n✅ Playwright E2E UI Test Completed Successfully!")

if __name__ == "__main__":
    run_e2e_tests()

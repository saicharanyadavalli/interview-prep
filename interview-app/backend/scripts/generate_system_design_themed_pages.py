"""Generate themed frontend lesson pages from local system design HTML files.

This script:
1) extracts article content from each saved chapter HTML,
2) rewrites asset paths to point to local source asset folders,
3) emits themed lesson pages under frontend/system-design/lessons,
4) updates frontend/assets/system-design/course-index.json local_html fields.
"""

from __future__ import annotations

from pathlib import Path
import json
import re


ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT / "interview-app" / "frontend"
SOURCE_ROOT = ROOT / "system design"
INDEX_PATH = FRONTEND_DIR / "assets" / "system-design" / "course-index.json"
OUTPUT_DIR = FRONTEND_DIR / "system-design" / "lessons"


def extract_article(raw_html: str) -> str:
    patterns = [
        r"<article[^>]*class=\"[^\"]*style_learnContent__K5K7M[^\"]*\"[^>]*>(.*?)</article>",
        r"<article[^>]*>(.*?)</article>",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    raise ValueError("Could not find article content")


def sanitize_article(article_html: str) -> str:
    cleaned = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        article_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"<style\b[^>]*>.*?</style>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Remove ByteByteGo completion button block.
    cleaned = re.sub(
        r"<div[^>]*class=\"[^\"]*style_markCompleteWrap[^\"]*\"[^>]*>.*?</div>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip()


def rewrite_asset_paths(article_html: str, step_no: int) -> str:
    assets_prefix = (
        f"../../../../system design/{step_no:02d}/"
        "ByteByteGo _ Technical Interview Prep_files/"
    )

    rewritten = article_html
    replacements = [
        ('"./ByteByteGo _ Technical Interview Prep_files/', f'"{assets_prefix}'),
        ("'./ByteByteGo _ Technical Interview Prep_files/", f"'{assets_prefix}"),
        ('"ByteByteGo _ Technical Interview Prep_files/', f'"{assets_prefix}'),
        ("'ByteByteGo _ Technical Interview Prep_files/", f"'{assets_prefix}"),
    ]

    for old, new in replacements:
        rewritten = rewritten.replace(old, new)

    return rewritten


def build_page(step_no: int, title: str, source_url: str, article_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{title} | System Design Course</title>
    <meta name=\"description\" content=\"System Design lesson {step_no}: {title}\" />
    <link rel=\"stylesheet\" href=\"../../css/global.css\" />
    <link rel=\"stylesheet\" href=\"../../css/components.css\" />
    <style>
      body {{
        margin: 0;
        background: var(--bg);
      }}

      .system-design-lesson-main {{
        max-width: 1100px;
        margin: 0 auto;
        padding: 1rem;
      }}

      .system-design-lesson-toolbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.6rem;
        flex-wrap: wrap;
        margin-bottom: 0.8rem;
      }}

      .system-design-lesson-header h1 {{
        margin-bottom: 0.3rem;
      }}

      .system-design-chapter-content table {{
        width: 100%;
        border-collapse: collapse;
        margin: 0.75rem 0;
      }}

      .system-design-chapter-content th,
      .system-design-chapter-content td {{
        border: 1px solid var(--line);
        padding: 0.5rem;
        vertical-align: top;
      }}

      .system-design-chapter-content figure img {{
        max-width: 100%;
      }}

      @media (max-width: 700px) {{
        .system-design-lesson-main {{
          padding: 0.75rem;
        }}
      }}
    </style>
  </head>
  <body data-theme=\"dark\" class=\"app-v2-theme\">
    <main class=\"system-design-lesson-main\">
      <section class=\"card-flat section\">
        <div class=\"system-design-lesson-toolbar\">
          <a class=\"btn btn-sm\" href=\"../../system-design.html\" target=\"_top\" rel=\"noopener noreferrer\">Back to Course</a>
          <a class=\"btn btn-sm btn-primary\" href=\"{source_url}\" target=\"_blank\" rel=\"noopener noreferrer\">Open Original</a>
        </div>
        <header class=\"system-design-lesson-header\">
          <h1>Step {step_no}: {title}</h1>
          <p class=\"text-sm text-muted\">System Design lesson {step_no} of 30</p>
        </header>
        <article class=\"system-design-chapter-content\">
{article_html}
        </article>
      </section>
    </main>
  </body>
</html>
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    index_data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    steps = index_data.get("steps", [])

    generated = 0
    for step in steps:
        step_no = int(step.get("step_no", 0) or 0)
        if step_no <= 0:
            continue

        source_file = SOURCE_ROOT / f"{step_no:02d}" / "ByteByteGo _ Technical Interview Prep.html"
        if not source_file.exists():
            raise FileNotFoundError(f"Missing source file: {source_file}")

        raw_html = source_file.read_text(encoding="utf-8", errors="ignore")
        article_html = extract_article(raw_html)
        article_html = sanitize_article(article_html)
        article_html = rewrite_asset_paths(article_html, step_no)

        title = str(step.get("title") or f"Step {step_no}").strip()
        source_url = str(step.get("source_url") or "").strip()

        page_html = build_page(step_no, title, source_url, article_html)
        output_file = OUTPUT_DIR / f"step-{step_no:02d}.html"
        output_file.write_text(page_html, encoding="utf-8")

        step["local_html"] = f"system-design/lessons/step-{step_no:02d}.html"
        generated += 1

    index_data["total_steps"] = len(steps)
    INDEX_PATH.write_text(json.dumps(index_data, indent=2) + "\n", encoding="utf-8")

    print(f"generated {generated} themed pages")


if __name__ == "__main__":
    main()

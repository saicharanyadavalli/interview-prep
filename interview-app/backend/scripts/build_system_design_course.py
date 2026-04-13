"""Build 30-step system design course assets from saved HTML chapters.

What this script does:
1) Reads chapter HTML files from ../system design/01..30.
2) Extracts the lesson article text/structure.
3) Converts non-SVG images to SVG wrappers (embedded data URI).
4) Uploads referenced images to Cloudinary CDN.
5) Writes per-step JSON files + one course index JSON for the frontend.

Usage:
    python backend/scripts/build_system_design_course.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import base64
import json
import re
from typing import Any

from bs4 import BeautifulSoup, Comment
import cloudinary
import cloudinary.uploader


ROOT_DIR = Path(__file__).resolve().parents[3]
SOURCE_DIR = ROOT_DIR / "system design"
TARGET_DIR = ROOT_DIR / "interview-app" / "frontend" / "assets" / "system-design"
TARGET_CHAPTERS_DIR = TARGET_DIR / "chapters"
TEMP_SVG_DIR = TARGET_DIR / ".tmp-svg-wrappers"
ENV_PATH = ROOT_DIR / "interview-app" / ".env"

START_STEP = 1
END_STEP = 30

ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "ul",
    "ol",
    "li",
    "pre",
    "code",
    "strong",
    "em",
    "a",
    "img",
    "figure",
    "figcaption",
    "blockquote",
    "hr",
    "br",
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip().lower())
    return value.strip("-") or "item"


def extract_source_url(soup: BeautifulSoup) -> str:
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        raw = str(comment)
        if "saved from url=" not in raw:
            continue
        match = re.search(r"https?://[^\s>]+", raw)
        if match:
            return match.group(0)
    return ""


def make_svg_wrapper_from_binary(image_path: Path, width: int = 1600, height: int = 900) -> str:
    ext = image_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")

    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return (
        "<svg xmlns=\"http://www.w3.org/2000/svg\" "
        f"width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\">"
        f"<image href=\"data:{mime};base64,{data}\" width=\"{width}\" height=\"{height}\" preserveAspectRatio=\"xMidYMid meet\"/>"
        "</svg>"
    )


def sanitize_article(article: BeautifulSoup) -> None:
    for bad in article.find_all(["script", "style", "noscript", "button"]):
        bad.decompose()

    for tag in list(article.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        attrs: dict[str, str] = {}
        if tag.name == "img":
            src = str(tag.get("src", "")).strip()
            alt = str(tag.get("alt", "")).strip()
            if src:
                attrs["src"] = src
            if alt:
                attrs["alt"] = alt
        elif tag.name == "a":
            href = str(tag.get("href", "")).strip()
            if href:
                attrs["href"] = href
                attrs["target"] = "_blank"
                attrs["rel"] = "noopener noreferrer"

        tag.attrs = attrs


@dataclass
class UploadContext:
    cloud_folder_root: str
    upload_cache: dict[str, str]


def upload_asset(local_path: Path, step_no: int, ctx: UploadContext) -> str:
    cache_key = f"{step_no}:{local_path.resolve()}"
    if cache_key in ctx.upload_cache:
        return ctx.upload_cache[cache_key]

    if not local_path.exists():
        ctx.upload_cache[cache_key] = ""
        return ""

    step_folder = f"step-{step_no:02d}"
    target_folder = f"{ctx.cloud_folder_root}/{step_folder}"
    ext = local_path.suffix.lower()

    upload_path = local_path
    public_id = slugify(local_path.stem)

    if ext != ".svg":
        TEMP_SVG_DIR.mkdir(parents=True, exist_ok=True)
        wrapped_name = f"{slugify(local_path.stem)}-{slugify(ext.lstrip('.'))}.svg"
        wrapped_path = TEMP_SVG_DIR / wrapped_name
        if not wrapped_path.exists():
            wrapped_svg = make_svg_wrapper_from_binary(local_path)
            wrapped_path.write_text(wrapped_svg, encoding="utf-8")
        upload_path = wrapped_path
        public_id = slugify(local_path.stem) + "-svg"

    result = cloudinary.uploader.upload(
        str(upload_path),
        folder=target_folder,
        public_id=public_id,
        overwrite=True,
        resource_type="image",
        unique_filename=False,
        use_filename=False,
    )
    secure_url = str(result.get("secure_url") or result.get("url") or "").strip()
    ctx.upload_cache[cache_key] = secure_url
    return secure_url


def chapter_file_path(step_no: int) -> Path:
    return SOURCE_DIR / f"{step_no:02d}" / "ByteByteGo _ Technical Interview Prep.html"


def chapter_assets_dir(step_no: int) -> Path:
    return SOURCE_DIR / f"{step_no:02d}" / "ByteByteGo _ Technical Interview Prep_files"


def process_step(step_no: int, ctx: UploadContext) -> dict[str, Any]:
    html_path = chapter_file_path(step_no)
    if not html_path.exists():
        raise FileNotFoundError(f"Missing chapter HTML: {html_path}")

    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    source_url = extract_source_url(soup)

    article = soup.find("article", class_="style_learnContent__K5K7M") or soup.find("article")
    if not article:
        raise ValueError(f"Could not find lesson article in {html_path}")

    title_node = article.find("h1") or soup.find("h1")
    title = title_node.get_text(" ", strip=True) if title_node else f"Step {step_no}"

    assets_dir = chapter_assets_dir(step_no)
    uploaded_count = 0

    for img in article.find_all("img"):
        src = str(img.get("src", "")).strip()
        if not src:
            continue

        relative = src.replace("./", "", 1).strip()
        local_path = assets_dir / Path(relative).name
        cdn_url = upload_asset(local_path, step_no, ctx)
        if cdn_url:
            img["src"] = cdn_url
            uploaded_count += 1

    sanitize_article(article)
    content_html = "".join(str(child) for child in article.children)
    plain_text = " ".join(article.get_text(" ", strip=True).split())

    summary = plain_text[:280]
    if len(plain_text) > 280:
        summary += "..."

    slug = source_url.rstrip("/").split("/")[-1] if source_url else slugify(title)

    chapter_payload = {
        "step_no": step_no,
        "title": title,
        "slug": slug,
        "source_url": source_url,
        "content_html": content_html,
        "word_count": len(plain_text.split()),
        "image_count": uploaded_count,
    }

    chapter_out = TARGET_CHAPTERS_DIR / f"step-{step_no:02d}.json"
    chapter_out.write_text(json.dumps(chapter_payload, indent=2), encoding="utf-8")

    return {
        "step_no": step_no,
        "title": title,
        "slug": slug,
        "summary": summary,
        "source_url": source_url,
        "chapter_file": f"assets/system-design/chapters/step-{step_no:02d}.json",
        "word_count": chapter_payload["word_count"],
        "image_count": uploaded_count,
    }


def main() -> None:
    TARGET_CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)

    env = read_env(ENV_PATH)
    cloud_name = env.get("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = env.get("CLOUDINARY_API_KEY", "").strip()
    api_secret = env.get("CLOUDINARY_API_SECRET", "").strip()
    cloud_folder_root = env.get("CLOUDINARY_SYSTEM_DESIGN_FOLDER", "interview-prep/system-design").strip()

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError("Cloudinary credentials are missing in interview-app/.env")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )

    ctx = UploadContext(cloud_folder_root=cloud_folder_root, upload_cache={})

    index_steps: list[dict[str, Any]] = []
    for step_no in range(START_STEP, END_STEP + 1):
        print(f"[build] step {step_no:02d}")
        index_steps.append(process_step(step_no, ctx))

    index_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_steps": len(index_steps),
        "steps": index_steps,
    }

    (TARGET_DIR / "course-index.json").write_text(
        json.dumps(index_payload, indent=2),
        encoding="utf-8",
    )

    print(f"[done] generated {len(index_steps)} steps")


if __name__ == "__main__":
    main()

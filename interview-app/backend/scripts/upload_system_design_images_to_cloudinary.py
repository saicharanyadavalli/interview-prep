"""Upload ordered system-design images to Cloudinary and optionally rewrite lesson HTML.

Usage:
  python scripts/upload_system_design_images_to_cloudinary.py
  python scripts/upload_system_design_images_to_cloudinary.py --rewrite-html

Environment variables read from interview-app/.env:
  CLOUDINARY_CLOUD_NAME
  CLOUDINARY_API_KEY
  CLOUDINARY_API_SECRET
  CLOUDINARY_SYSTEM_DESIGN_FOLDER (optional, default: interview-assistant/system-design)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import argparse
import json
import re

import cloudinary
import cloudinary.uploader


ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / "interview-app" / ".env"
ORDERED_IMAGES_ROOT = (
    ROOT / "interview-app" / "frontend" / "assets" / "system-design" / "ordered-images"
)
LESSONS_DIR = ROOT / "interview-app" / "frontend" / "system-design" / "lessons"
MAP_PATH = ORDERED_IMAGES_ROOT / "cloudinary-map.json"
REPORT_PATH = ORDERED_IMAGES_ROOT / "cloudinary-upload-report.json"

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", flags=re.IGNORECASE)
SRC_ATTR_RE = re.compile(r"\bsrc\s*=\s*(['\"])(.*?)\1", flags=re.IGNORECASE | re.DOTALL)
STRIP_ATTR_RE = re.compile(r"\s(?:srcset|sizes)\s*=\s*(\".*?\"|'.*?')", flags=re.IGNORECASE | re.DOTALL)
ALT_ATTR_RE = re.compile(r"\balt\s*=\s*(['\"])(.*?)\1", flags=re.IGNORECASE | re.DOTALL)
STEP_IMAGE_KEY_RE = re.compile(
    r"/(step-\d{2}/[^/?#]+\.(?:png|jpg|jpeg|webp|gif|svg))$",
    flags=re.IGNORECASE,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


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


def configure_cloudinary_from_env() -> str:
    env = read_env(ENV_PATH)

    cloud_name = env.get("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = env.get("CLOUDINARY_API_KEY", "").strip()
    api_secret = env.get("CLOUDINARY_API_SECRET", "").strip()
    base_folder = env.get(
        "CLOUDINARY_SYSTEM_DESIGN_FOLDER",
        "interview-assistant/system-design",
    ).strip("/")

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError(
            "Missing Cloudinary credentials. Set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in interview-app/.env"
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )

    return base_folder


def upload_images(base_folder: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    if not ORDERED_IMAGES_ROOT.exists():
        raise RuntimeError(f"Ordered images folder not found: {ORDERED_IMAGES_ROOT}")

    mapping: dict[str, str] = {}
    report_items: list[dict[str, str]] = []

    step_dirs = sorted(path for path in ORDERED_IMAGES_ROOT.glob("step-*") if path.is_dir())
    all_image_files: list[Path] = []
    for step_dir in step_dirs:
        for image_file in sorted(step_dir.iterdir()):
            if image_file.is_file() and image_file.suffix.lower() in IMAGE_EXTENSIONS:
                all_image_files.append(image_file)

    total_images = len(all_image_files)
    uploaded_count = 0
    print(f"starting upload of {total_images} images to Cloudinary")

    for step_dir in step_dirs:
        cloud_folder = f"{base_folder}/{step_dir.name}"

        for image_file in sorted(step_dir.iterdir()):
            if not image_file.is_file() or image_file.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            relative_path = image_file.relative_to(ORDERED_IMAGES_ROOT).as_posix()
            public_id = image_file.stem

            result = cloudinary.uploader.upload(
                str(image_file),
                folder=cloud_folder,
                public_id=public_id,
                overwrite=True,
                resource_type="image",
                unique_filename=False,
                use_filename=False,
            )

            secure_url = str(result.get("secure_url") or result.get("url") or "").strip()
            if not secure_url:
                raise RuntimeError(f"Cloudinary upload returned no URL for: {relative_path}")

            mapping[relative_path] = secure_url
            report_items.append(
                {
                    "relative_path": relative_path,
                    "cloud_folder": cloud_folder,
                    "public_id": public_id,
                    "url": secure_url,
                }
            )

            uploaded_count += 1
            if uploaded_count % 25 == 0 or uploaded_count == total_images:
                print(f"uploaded {uploaded_count}/{total_images}")

    return mapping, report_items


def extract_ordered_image_key(src: str) -> str | None:
    parsed = urlparse(src)
    if parsed.scheme in {"data", "blob"}:
        return None

    path_source = parsed.path if parsed.scheme in {"http", "https"} else src
    path = path_source.replace("\\", "/")
    marker = "assets/system-design/ordered-images/"
    index = path.find(marker)
    if index >= 0:
        relative = path[index + len(marker) :].strip("/")
        return relative or None

    cloud_match = STEP_IMAGE_KEY_RE.search(path)
    if cloud_match:
        return cloud_match.group(1)

    return None


def build_short_alt(key: str | None) -> str:
    if not key:
        return "System design illustration"

    stem = Path(key).stem
    stem = re.sub(r"^\d+-", "", stem)
    stem = re.sub(r"-[A-Z0-9]{6,}$", "", stem)
    text = stem.replace("-", " ").strip()

    if not text:
        return "System design illustration"

    return text.capitalize()


def normalize_img_alt(tag: str, key: str | None) -> tuple[str, bool]:
    short_alt = build_short_alt(key)
    alt_match = ALT_ATTR_RE.search(tag)
    if not alt_match:
        return tag.replace("<img", f'<img alt="{short_alt}"', 1), True

    current_alt = alt_match.group(2).strip()
    if len(current_alt) <= 160:
        return tag, False

    updated = ALT_ATTR_RE.sub(f'alt="{short_alt}"', tag, count=1)
    return updated, True


def rewrite_lessons_to_cloudinary(mapping: dict[str, str]) -> int:
    rewritten_count = 0

    for lesson_file in sorted(LESSONS_DIR.glob("step-*.html")):
        html = lesson_file.read_text(encoding="utf-8", errors="ignore")
        changed = False

        def replace_img(match: re.Match[str]) -> str:
            nonlocal changed
            tag = match.group(0)
            tag_no_srcset = STRIP_ATTR_RE.sub("", tag)

            src_match = SRC_ATTR_RE.search(tag_no_srcset)
            if not src_match:
                normalized_tag, alt_changed = normalize_img_alt(tag_no_srcset, None)
                if alt_changed:
                    changed = True
                return normalized_tag

            old_src = src_match.group(2).strip()
            key = extract_ordered_image_key(old_src)
            if not key:
                normalized_tag, alt_changed = normalize_img_alt(tag_no_srcset, None)
                if alt_changed:
                    changed = True
                return normalized_tag

            cloud_url = mapping.get(key)
            if not cloud_url:
                normalized_tag, alt_changed = normalize_img_alt(tag_no_srcset, key)
                if alt_changed:
                    changed = True
                return normalized_tag

            changed = True
            updated_tag = SRC_ATTR_RE.sub(f'src="{cloud_url}"', tag_no_srcset, count=1)
            normalized_tag, alt_changed = normalize_img_alt(updated_tag, key)
            if alt_changed:
                changed = True
            return normalized_tag

        rewritten_html = IMG_TAG_RE.sub(replace_img, html)
        if changed:
            lesson_file.write_text(rewritten_html, encoding="utf-8")
            rewritten_count += 1

    return rewritten_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rewrite-html",
        action="store_true",
        help="Rewrite lesson image src attributes to Cloudinary URLs after upload.",
    )
    args = parser.parse_args()

    base_folder = configure_cloudinary_from_env()
    mapping, report_items = upload_images(base_folder)

    map_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_folder": base_folder,
        "count": len(mapping),
        "mapping": mapping,
    }
    MAP_PATH.write_text(json.dumps(map_payload, indent=2) + "\n", encoding="utf-8")

    report_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(report_items),
        "items": report_items,
    }
    REPORT_PATH.write_text(json.dumps(report_payload, indent=2) + "\n", encoding="utf-8")

    rewritten = 0
    if args.rewrite_html:
        rewritten = rewrite_lessons_to_cloudinary(mapping)

    print(f"uploaded images: {len(mapping)}")
    print(f"map file: {MAP_PATH}")
    print(f"report file: {REPORT_PATH}")
    if args.rewrite_html:
        print(f"rewritten lesson files: {rewritten}")


if __name__ == "__main__":
    main()

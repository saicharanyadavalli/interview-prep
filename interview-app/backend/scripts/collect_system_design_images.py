"""Collect and normalize system design lesson images.

This script creates one consolidated image root folder under frontend assets,
organized by step, then rewrites lesson pages to use those copied assets.
It also removes srcset/sizes attributes that can override local src values.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import json
import re
import shutil


ROOT = Path(__file__).resolve().parents[3]
LESSONS_DIR = ROOT / "interview-app" / "frontend" / "system-design" / "lessons"
OUTPUT_ROOT = ROOT / "interview-app" / "frontend" / "assets" / "system-design" / "ordered-images"
MANIFEST_PATH = OUTPUT_ROOT / "image-manifest.json"

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", flags=re.IGNORECASE)
SRC_ATTR_RE = re.compile(r"\bsrc\s*=\s*(['\"])(.*?)\1", flags=re.IGNORECASE | re.DOTALL)
STRIP_ATTR_RE = re.compile(r"\s(?:srcset|sizes)\s*=\s*(\".*?\"|'.*?')", flags=re.IGNORECASE | re.DOTALL)
STEP_FILE_RE = re.compile(r"^step-(\d{2})\.html$", flags=re.IGNORECASE)


def pick_best_file(files: list[Path], preferred_suffix: str = "") -> Path | None:
    if not files:
        return None

    if preferred_suffix:
        for candidate in files:
            if candidate.suffix.lower() == preferred_suffix.lower():
                return candidate

    priority = {".svg": 0, ".webp": 1, ".png": 2, ".jpg": 3, ".jpeg": 4, ".gif": 5}
    ranked = sorted(
        files,
        key=lambda p: (priority.get(p.suffix.lower(), 9), p.name.lower()),
    )
    return ranked[0]


def find_source_file(src: str, lesson_file: Path, step_assets_dir: Path) -> Path | None:
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https", "data", "blob"}:
        return None

    src_path = unquote(parsed.path or "")
    preferred_suffix = Path(src_path).suffix

    if src_path:
        direct = (lesson_file.parent / src_path).resolve()
        if direct.exists() and direct.is_file():
            return direct

        stem_matches = list(direct.parent.glob(f"{direct.stem}.*"))
        best = pick_best_file(stem_matches, preferred_suffix=preferred_suffix)
        if best:
            return best

    query_values = parse_qs(parsed.query).get("url", [])
    for value in query_values:
        decoded = unquote(value)
        parsed_decoded = urlparse(decoded)
        candidate_name = Path(parsed_decoded.path).name or Path(decoded).name
        if not candidate_name:
            continue

        candidate = step_assets_dir / candidate_name
        if candidate.exists() and candidate.is_file():
            return candidate

        stem_matches = list(step_assets_dir.glob(f"{Path(candidate_name).stem}.*"))
        best = pick_best_file(stem_matches, preferred_suffix=Path(candidate_name).suffix)
        if best:
            return best

    base_name = Path(src_path).name
    if base_name:
        candidate = step_assets_dir / base_name
        if candidate.exists() and candidate.is_file():
            return candidate

        stem_matches = list(step_assets_dir.glob(f"{Path(base_name).stem}.*"))
        best = pick_best_file(stem_matches, preferred_suffix=Path(base_name).suffix)
        if best:
            return best

    return None


def main() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "generated_for": "system-design-lessons",
        "base_folder": "assets/system-design/ordered-images",
        "steps": [],
        "unresolved": [],
    }

    unresolved: list[dict[str, str]] = []

    for lesson_file in sorted(LESSONS_DIR.glob("step-*.html")):
        step_match = STEP_FILE_RE.match(lesson_file.name)
        if not step_match:
            continue

        step_no = int(step_match.group(1))
        step_code = f"{step_no:02d}"
        step_assets_dir = (
            ROOT
            / "system design"
            / step_code
            / "ByteByteGo _ Technical Interview Prep_files"
        )
        step_output_dir = OUTPUT_ROOT / f"step-{step_code}"
        step_output_dir.mkdir(parents=True, exist_ok=True)

        html = lesson_file.read_text(encoding="utf-8", errors="ignore")

        image_counter = 0
        copied_by_source: dict[str, str] = {}
        step_images: list[dict[str, str]] = []

        def replace_img(match: re.Match[str]) -> str:
            nonlocal image_counter

            tag = match.group(0)
            src_match = SRC_ATTR_RE.search(tag)
            if not src_match:
                return tag

            original_src = src_match.group(2).strip()
            tag_no_srcset = STRIP_ATTR_RE.sub("", tag)

            source_file = find_source_file(original_src, lesson_file, step_assets_dir)
            if source_file is None:
                unresolved.append(
                    {
                        "step": step_code,
                        "lesson": lesson_file.name,
                        "src": original_src,
                    }
                )
                return tag_no_srcset

            source_key = str(source_file.resolve())
            if source_key not in copied_by_source:
                image_counter += 1
                dest_name = f"{image_counter:03d}-{source_file.name}"
                destination = step_output_dir / dest_name
                shutil.copy2(source_file, destination)
                copied_by_source[source_key] = dest_name

                step_images.append(
                    {
                        "order": image_counter,
                        "file": f"step-{step_code}/{dest_name}",
                        "source": source_file.name,
                        "lesson": lesson_file.name,
                    }
                )

            dest_name = copied_by_source[source_key]
            new_src = f"../../assets/system-design/ordered-images/step-{step_code}/{dest_name}"

            updated = SRC_ATTR_RE.sub(
                f'src="{new_src}"',
                tag_no_srcset,
                count=1,
            )
            return updated

        rewritten = IMG_TAG_RE.sub(replace_img, html)
        lesson_file.write_text(rewritten, encoding="utf-8")

        manifest["steps"].append(
            {
                "step": step_code,
                "lesson": lesson_file.name,
                "image_count": len(step_images),
                "images": step_images,
            }
        )

    manifest["unresolved"] = unresolved
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"processed lessons: {len(list(LESSONS_DIR.glob('step-*.html')))}")
    print(f"unresolved image refs: {len(unresolved)}")
    print(f"manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

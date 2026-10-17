#!/usr/bin/env python3
"""Amazon RDS Course Lessons Loader Utility.

Loads interactive course lessons from sqlbolt_courses.json into the
authoritative Amazon RDS PostgreSQL table 'course_lessons'.

Connects via backend/services/rds_client.py or DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Sequence
from dotenv import load_dotenv

script_dir = Path(__file__).parent.resolve()
app_dir = script_dir.parent.resolve()
backend_dir = app_dir / "backend"
sys.path.insert(0, str(backend_dir))

if (app_dir / ".env").exists():
    load_dotenv(app_dir / ".env")
elif (backend_dir / ".env").exists():
    load_dotenv(backend_dir / ".env")
else:
    load_dotenv()

from services import rds_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("load_courses")


def validate_lesson_data(lessons: list) -> list[str]:
    """Validate lesson structure, ordering, and required fields.

    Returns a list of validation error messages, or an empty list if valid.
    """
    errors: list[str] = []
    if not isinstance(lessons, list):
        return ["Course data must be a JSON array of lesson objects."]

    seen_orders: set[int] = set()
    for idx, item in enumerate(lessons):
        if not isinstance(item, dict):
            errors.append(f"Lesson at index {idx} is not a JSON object.")
            continue

        order = item.get("order")
        if order is None or not isinstance(order, int) or order < 1:
            errors.append(f"Lesson at index {idx} ('{item.get('title')}') has invalid or missing 'order': {order}")
        elif order in seen_orders:
            errors.append(f"Duplicate order {order} detected at lesson index {idx}.")
        else:
            seen_orders.add(order)

        title = item.get("title")
        if not title or not str(title).strip():
            errors.append(f"Lesson at index {idx} has missing or empty title.")

    return errors


def load_courses(
    json_path: Path | str | None = None,
    track_ids: Sequence[str] = ("sql-course",),
    dry_run: bool = False,
    validate_only: bool = False,
) -> dict[str, int]:
    """Load interactive course lessons into RDS table course_lessons.

    Args:
        json_path: Optional path to JSON source file. Defaults to sqlbolt_courses.json.
        track_ids: Target track identifiers to populate. Defaults to canonical 'sql-course'.
        dry_run: If True, validate and log actions without executing database mutations.
        validate_only: If True, perform schema and structure validation without DB interaction.

    Returns:
        dict with counts: {"synced": int, "failed": int, "total": int}
    """
    target_path = Path(json_path) if json_path else script_dir / "sqlbolt_courses.json"
    if not target_path.exists():
        raise FileNotFoundError(f"Courses JSON file not found at {target_path}")

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            lessons_data = json.load(f)
    except json.JSONDecodeError as err:
        logger.error("Failed to parse course JSON at %s: %s", target_path, err)
        raise ValueError(f"Malformed JSON in course file {target_path}: {err}") from err

    logger.info("Loaded %d lessons from %s", len(lessons_data), target_path.name)

    # Validate lesson records
    val_errors = validate_lesson_data(lessons_data)
    if val_errors:
        for err in val_errors:
            logger.error("Validation error: %s", err)
        if validate_only:
            return {"synced": 0, "failed": len(val_errors), "total": len(lessons_data)}
        raise ValueError(f"Lesson validation failed with {len(val_errors)} errors: {val_errors[0]}")

    if validate_only:
        logger.info("Validation passed successfully for %d lessons.", len(lessons_data))
        return {"synced": len(lessons_data), "failed": 0, "total": len(lessons_data)}

    total_operations = len(lessons_data) * len(track_ids)
    overall_synced = 0
    overall_failed = 0

    for track_id in track_ids:
        track_synced = 0
        track_failed = 0

        for lesson in lessons_data:
            step_no = int(lesson.get("order", 0))
            title = str(lesson.get("title", f"Lesson {step_no}")).strip()
            content = str(lesson.get("content_markdown", "")).strip()

            if dry_run:
                logger.info("[DRY-RUN] Would upsert track='%s', step=%d, title='%s'", track_id, step_no, title)
                track_synced += 1
                continue

            try:
                rds_client.mutate(
                    """
                    INSERT INTO course_lessons (track_id, step_no, title, html_content)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (track_id, step_no)
                    DO UPDATE SET title = EXCLUDED.title, html_content = EXCLUDED.html_content;
                    """,
                    (track_id, step_no, title, content),
                )
                track_synced += 1
            except Exception as exc:
                logger.error("Failed to sync lesson %d for track '%s': %s", step_no, track_id, exc)
                track_failed += 1

        logger.info("Track '%s' sync result: %d succeeded, %d failed", track_id, track_synced, track_failed)
        overall_synced += track_synced
        overall_failed += track_failed

    logger.info(
        "Course loading summary: %d succeeded, %d failed across %d total operations",
        overall_synced,
        overall_failed,
        total_operations,
    )
    return {"synced": overall_synced, "failed": overall_failed, "total": total_operations}


def parse_args():
    parser = argparse.ArgumentParser(description="Load interactive course lessons into Amazon RDS.")
    parser.add_argument("--json-path", type=str, default=None, help="Path to course JSON file.")
    parser.add_argument(
        "--track-id",
        type=str,
        default="sql-course",
        help="Canonical track identifier to populate (default: sql-course).",
    )
    parser.add_argument(
        "--include-legacy-alias",
        action="store_true",
        help="Also populate legacy 'sql-tutorial' track identifier.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without modifying the database.")
    parser.add_argument("--validate-only", action="store_true", help="Validate course JSON schema only.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    targets = [args.track_id]
    if args.include_legacy_alias and "sql-tutorial" not in targets:
        targets.append("sql-tutorial")

    try:
        result = load_courses(
            json_path=args.json_path,
            track_ids=targets,
            dry_run=args.dry_run,
            validate_only=args.validate_only,
        )
        if result.get("failed", 0) > 0:
            logger.error("Course loading finished with %d failures.", result["failed"])
            sys.exit(1)
        logger.info("Course loading completed successfully.")
        sys.exit(0)
    except Exception as e:
        logger.fatal("Fatal error during course loading: %s", e)
        sys.exit(1)

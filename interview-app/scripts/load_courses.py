#!/usr/bin/env python3
"""Amazon RDS Course Lessons Loader Utility.

Loads interactive course lessons from sqlbolt_courses.json into the
authoritative Amazon RDS PostgreSQL table 'course_lessons'.

Connects via backend/services/rds_client.py or DATABASE_URL.
"""

from __future__ import annotations

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


def load_courses(
    json_path: Path | str | None = None,
    track_ids: Sequence[str] = ("sql-course", "sql-tutorial"),
) -> dict[str, int]:
    """Load interactive course lessons into RDS table course_lessons.

    Args:
        json_path: Optional path to JSON source file. Defaults to sqlbolt_courses.json.
        track_ids: Target track identifiers to populate. Defaults to both canonical
                   'sql-course' and legacy alias 'sql-tutorial'.

    Returns:
        dict with counts: {"synced": int, "failed": int, "total": int}
    """
    target_path = Path(json_path) if json_path else script_dir / "sqlbolt_courses.json"
    if not target_path.exists():
        raise FileNotFoundError(f"Courses JSON file not found at {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        lessons_data = json.load(f)

    logger.info("Loaded %d lessons from %s", len(lessons_data), target_path.name)

    synced = 0
    failed = 0
    total_operations = len(lessons_data) * len(track_ids)

    for track_id in track_ids:
        for lesson in lessons_data:
            step_no = int(lesson.get("order", 0))
            title = lesson.get("title", f"Lesson {step_no}")
            content = lesson.get("content_markdown", "")

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
                synced += 1
            except Exception as exc:
                logger.error("Failed to sync lesson %d for track '%s': %s", step_no, track_id, exc)
                failed += 1

        logger.info("Synced track '%s' (success: %d, failed: %d)", track_id, synced, failed)

    return {"synced": synced, "failed": failed, "total": total_operations}


if __name__ == "__main__":
    result = load_courses()
    logger.info("Course loading complete: %s", result)

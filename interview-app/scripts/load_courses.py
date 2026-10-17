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

from services.rds_client import rds_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("load_courses")


def load_courses():
    json_path = script_dir / "sqlbolt_courses.json"
    if not json_path.exists():
        raise FileNotFoundError(f"Courses JSON file not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        lessons_data = json.load(f)

    logger.info("Loaded %d lessons from %s", len(lessons_data), json_path.name)

    track_id = "sql-tutorial"
    synced = 0

    for lesson in lessons_data:
        step_no = int(lesson.get("order", 0))
        title = lesson.get("title", f"Lesson {step_no}")
        content = lesson.get("content_markdown", "")

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

    logger.info("Successfully synced %d course lessons for track '%s' into RDS.", synced, track_id)


if __name__ == "__main__":
    load_courses()

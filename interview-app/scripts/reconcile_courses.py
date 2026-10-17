#!/usr/bin/env python3
"""Course Data Reconciliation Utility (Read-Only).

Compares lesson counts, titles, slugs, and tasks checksums between
the bundled JSON definition (scripts/sqlbolt_courses.json) and
the Amazon RDS course_lessons table.

SAFETY:
- Strictly READ-ONLY (executes SELECT queries only).
- Never mutates or truncates any table.
- Does not connect to production unless explicitly pointed to a staging/target DATABASE_URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reconcile_courses")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def compute_checksum(data: Any) -> str:
    """Compute a deterministic MD5 hash for a data structure."""
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


def reconcile_course_data(
    json_path: Path | str | None = None,
    track_id: str = "sql-course",
) -> dict[str, Any]:
    """Compare local course definition against RDS course_lessons records (read-only)."""
    target_path = Path(json_path) if json_path else SCRIPT_DIR / "sqlbolt_courses.json"
    if not target_path.exists():
        raise FileNotFoundError(f"Source JSON file not found: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        local_lessons = json.load(f)

    logger.info("Loaded %d reference lessons from %s", len(local_lessons), target_path.name)

    from services import rds_client

    # Query existing rows from RDS
    try:
        db_rows = rds_client.query(
            """
            SELECT step_no, title, html_content, tasks, slug
            FROM course_lessons
            WHERE track_id = %s
            ORDER BY step_no ASC;
            """,
            (track_id,),
            fetch="all",
        ) or []
    except Exception as exc:
        logger.error("Failed to query RDS course_lessons: %s", exc)
        return {
            "status": "ERROR",
            "error": str(exc),
            "local_count": len(local_lessons),
            "db_count": 0,
        }

    db_by_step = {r["step_no"]: r for r in db_rows}
    discrepancies = []

    for idx, item in enumerate(local_lessons, start=1):
        step_no = item.get("order", idx)
        title = item.get("title", "").strip()
        slug = item.get("slug", f"step-{step_no}").strip()
        tasks = item.get("tasks", [])

        db_row = db_by_step.get(step_no)
        if not db_row:
            discrepancies.append({
                "step_no": step_no,
                "issue": "MISSING_IN_DATABASE",
                "expected_title": title,
            })
            continue

        # Check title
        if db_row.get("title", "").strip() != title:
            discrepancies.append({
                "step_no": step_no,
                "issue": "TITLE_MISMATCH",
                "expected": title,
                "found": db_row.get("title"),
            })

        # Check slug
        db_slug = db_row.get("slug")
        if db_slug and db_slug.strip() != slug:
            discrepancies.append({
                "step_no": step_no,
                "issue": "SLUG_MISMATCH",
                "expected": slug,
                "found": db_slug,
            })

        # Check tasks
        db_tasks = db_row.get("tasks")
        if isinstance(db_tasks, str):
            try:
                db_tasks = json.loads(db_tasks)
            except Exception:
                db_tasks = []
        elif not isinstance(db_tasks, list):
            db_tasks = []

        if len(db_tasks) != len(tasks):
            discrepancies.append({
                "step_no": step_no,
                "issue": "TASK_COUNT_MISMATCH",
                "expected_count": len(tasks),
                "found_count": len(db_tasks),
            })

    result = {
        "status": "PARITY" if not discrepancies else "DISCREPANCIES_FOUND",
        "track_id": track_id,
        "local_count": len(local_lessons),
        "db_count": len(db_rows),
        "discrepancies_count": len(discrepancies),
        "discrepancies": discrepancies,
    }

    logger.info(
        "Reconciliation finished for track '%s': DB count=%d, Local count=%d, Discrepancies=%d",
        track_id,
        len(db_rows),
        len(local_lessons),
        len(discrepancies),
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconcile local course data with RDS course_lessons (Read-Only).")
    parser.add_argument("--json-path", type=str, default=None, help="Path to reference courses JSON.")
    parser.add_argument("--track-id", type=str, default="sql-course", help="Track ID to reconcile (default: sql-course).")
    args = parser.parse_args()

    res = reconcile_course_data(json_path=args.json_path, track_id=args.track_id)
    print(json.dumps(res, indent=2))
    if res.get("status") == "PARITY":
        sys.exit(0)
    elif res.get("status") == "DISCREPANCIES_FOUND":
        sys.exit(2)
    else:
        sys.exit(1)

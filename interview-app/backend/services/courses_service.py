"""Courses Service — business logic for courses, lessons, progress, and SQL seed data."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.supabase_client import get_supabase_client

# Path to sqlbolt_courses.json
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
SQLBOLT_JSON_PATH = PROJECT_DIR / "scripts" / "sqlbolt_courses.json"

# In-memory user progress store for fallback / testing
_IN_MEMORY_USER_PROGRESS: dict[str, set[str]] = {}

COURSE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "c0000000-0000-0000-0000-000000000001",
        "slug": "system-design",
        "track_id": "system-design",
        "title": "System Design Fundamentals",
        "description": "Master large-scale distributed system design principles, microservices, and interview patterns with 30 in-depth architectural breakdowns.",
        "icon": "Layers",
    },
    {
        "id": "c0000000-0000-0000-0000-000000000002",
        "slug": "genai-system-design",
        "track_id": "genai-system-design",
        "title": "Generative AI System Design",
        "description": "Design cutting-edge GenAI architectures including ChatGPT chatbots, RAG pipelines, Diffusion models, and Multimodal video synthesis.",
        "icon": "Sparkles",
    },
    {
        "id": "c0000000-0000-0000-0000-000000000003",
        "slug": "ml-system-design",
        "track_id": "ml-system-design",
        "title": "Machine Learning System Design",
        "description": "Architect real-world ML systems including Visual Search, YouTube Video Recommendations, and Real-time Ad Click Prediction.",
        "icon": "Cpu",
    },
    {
        "id": "c0000000-0000-0000-0000-000000000004",
        "slug": "mobile-system-design",
        "track_id": "mobile-system-design",
        "title": "Mobile System Design",
        "description": "Master end-to-end mobile architecture for high-performance apps, offline caching, push notifications, and real-time news feeds.",
        "icon": "Smartphone",
    },
    {
        "id": "c0000000-0000-0000-0000-000000000005",
        "slug": "object-oriented-design",
        "track_id": "object-oriented-design",
        "title": "Object-Oriented Design (OOD)",
        "description": "Learn design patterns, SOLID principles, and complete class-diagram implementations for classic interview problems like Parking Lot and Elevator.",
        "icon": "Boxes",
    },
    {
        "id": "c0000000-0000-0000-0000-000000000006",
        "slug": "sql-course",
        "track_id": "sql-course",
        "title": "SQL Practice Course",
        "description": "Master SQL queries step-by-step with interactive sql.js practice tables and exercises.",
        "icon": "Database",
    },
]


def _normalize_track_id(slug: str) -> str:
    s = slug.strip().lower()
    if s in ("sql", "sql-tutorial", "sql-course"):
        return "sql-course"
    if s in ("system-design", "system_design"):
        return "system-design"
    if s in ("genai-system-design", "genai_system_design", "gen-ai-system-design"):
        return "genai-system-design"
    if s in ("ml-system-design", "ml_system_design"):
        return "ml-system-design"
    if s in ("mobile-system-design", "mobile_system_design"):
        return "mobile-system-design"
    if s in ("object-oriented-design", "object_oriented_design", "ood"):
        return "object-oriented-design"
    return s


def get_sql_seed_tables() -> list[dict[str, Any]]:
    """Return DDL statements and initial data for SQL practice tables."""
    return [
        {
            "name": "Movies",
            "schema_sql": (
                "CREATE TABLE Movies (\n"
                "  Id INTEGER PRIMARY KEY,\n"
                "  Title TEXT NOT NULL,\n"
                "  Director TEXT NOT NULL,\n"
                "  Year INTEGER NOT NULL,\n"
                "  Length_minutes INTEGER NOT NULL\n"
                ");"
            ),
            "insert_sql": (
                "INSERT INTO Movies (Id, Title, Director, Year, Length_minutes) VALUES\n"
                "(1, 'Toy Story', 'John Lasseter', 1995, 81),\n"
                "(2, 'A Bug''s Life', 'John Lasseter', 1998, 95),\n"
                "(3, 'Toy Story 2', 'John Lasseter', 1999, 92),\n"
                "(4, 'Monsters, Inc.', 'Pete Docter', 2001, 92),\n"
                "(5, 'Finding Nemo', 'Andrew Stanton', 2003, 100),\n"
                "(6, 'The Incredibles', 'Brad Bird', 2004, 115),\n"
                "(7, 'Cars', 'John Lasseter', 2006, 117),\n"
                "(8, 'Ratatouille', 'Brad Bird', 2007, 111),\n"
                "(9, 'WALL-E', 'Andrew Stanton', 2008, 98),\n"
                "(10, 'Up', 'Pete Docter', 2009, 96),\n"
                "(11, 'Toy Story 3', 'Lee Unkrich', 2010, 103),\n"
                "(12, 'Cars 2', 'John Lasseter', 2011, 106),\n"
                "(13, 'Brave', 'Mark Andrews', 2012, 102),\n"
                "(14, 'Monsters University', 'Dan Scanlon', 2013, 104);"
            ),
            "columns": ["Id", "Title", "Director", "Year", "Length_minutes"],
            "rows": [
                [1, "Toy Story", "John Lasseter", 1995, 81],
                [2, "A Bug's Life", "John Lasseter", 1998, 95],
                [3, "Toy Story 2", "John Lasseter", 1999, 92],
                [4, "Monsters, Inc.", "Pete Docter", 2001, 92],
                [5, "Finding Nemo", "Andrew Stanton", 2003, 100],
                [6, "The Incredibles", "Brad Bird", 2004, 115],
                [7, "Cars", "John Lasseter", 2006, 117],
                [8, "Ratatouille", "Brad Bird", 2007, 111],
                [9, "WALL-E", "Andrew Stanton", 2008, 98],
                [10, "Up", "Pete Docter", 2009, 96],
                [11, "Toy Story 3", "Lee Unkrich", 2010, 103],
                [12, "Cars 2", "John Lasseter", 2011, 106],
                [13, "Brave", "Mark Andrews", 2012, 102],
                [14, "Monsters University", "Dan Scanlon", 2013, 104],
            ],
        },
        {
            "name": "Boxoffice",
            "schema_sql": (
                "CREATE TABLE Boxoffice (\n"
                "  Movie_id INTEGER PRIMARY KEY REFERENCES Movies(Id),\n"
                "  Rating REAL NOT NULL,\n"
                "  Domestic_sales INTEGER NOT NULL,\n"
                "  International_sales INTEGER NOT NULL\n"
                ");"
            ),
            "insert_sql": (
                "INSERT INTO Boxoffice (Movie_id, Rating, Domestic_sales, International_sales) VALUES\n"
                "(5, 8.2, 380843261, 555900000),\n"
                "(14, 7.4, 268492764, 475066841),\n"
                "(8, 8.0, 206445654, 417282858),\n"
                "(12, 6.4, 191452396, 368400000),\n"
                "(3, 7.9, 245852179, 251600000),\n"
                "(6, 8.0, 261441092, 370001000),\n"
                "(9, 8.4, 223808164, 297500000),\n"
                "(11, 8.4, 415004880, 651964882),\n"
                "(1, 8.3, 191796233, 170162500),\n"
                "(7, 7.2, 244082982, 217900000),\n"
                "(10, 8.3, 293004164, 438338580),\n"
                "(4, 8.1, 289916256, 272900000),\n"
                "(2, 7.2, 162798565, 200600000),\n"
                "(13, 7.2, 237282182, 303165085);"
            ),
            "columns": ["Movie_id", "Rating", "Domestic_sales", "International_sales"],
            "rows": [
                [5, 8.2, 380843261, 555900000],
                [14, 7.4, 268492764, 475066841],
                [8, 8.0, 206445654, 417282858],
                [12, 6.4, 191452396, 368400000],
                [3, 7.9, 245852179, 251600000],
                [6, 8.0, 261441092, 370001000],
                [9, 8.4, 223808164, 297500000],
                [11, 8.4, 415004880, 651964882],
                [1, 8.3, 191796233, 170162500],
                [7, 7.2, 244082982, 217900000],
                [10, 8.3, 293004164, 438338580],
                [4, 8.1, 289916256, 272900000],
                [2, 7.2, 162798565, 200600000],
                [13, 7.2, 237282182, 303165085],
            ],
        },
        {
            "name": "Buildings",
            "schema_sql": (
                "CREATE TABLE Buildings (\n"
                "  Building_name TEXT PRIMARY KEY,\n"
                "  Capacity INTEGER NOT NULL\n"
                ");"
            ),
            "insert_sql": (
                "INSERT INTO Buildings (Building_name, Capacity) VALUES\n"
                "('1e', 24),\n"
                "('1w', 32),\n"
                "('2e', 16),\n"
                "('2w', 20);"
            ),
            "columns": ["Building_name", "Capacity"],
            "rows": [
                ["1e", 24],
                ["1w", 32],
                ["2e", 16],
                ["2w", 20],
            ],
        },
        {
            "name": "Employees",
            "schema_sql": (
                "CREATE TABLE Employees (\n"
                "  Role TEXT NOT NULL,\n"
                "  Name TEXT PRIMARY KEY,\n"
                "  Building TEXT,\n"
                "  Years_employed INTEGER NOT NULL\n"
                ");"
            ),
            "insert_sql": (
                "INSERT INTO Employees (Role, Name, Building, Years_employed) VALUES\n"
                "('Engineer', 'Becky A.', '1e', 4),\n"
                "('Engineer', 'Dan B.', '1e', 2),\n"
                "('Engineer', 'Sharon F.', '1e', 6),\n"
                "('Engineer', 'Dan M.', '1e', 4),\n"
                "('Engineer', 'Malik S.', '1e', 1),\n"
                "('Manager', 'Yair L.', '1e', 10),\n"
                "('Manager', 'Katrina M.', '2w', 6),\n"
                "('Manager', 'Shirley P.', '2w', 3),\n"
                "('Manager', 'Brian M.', '1e', 9),\n"
                "('Artist', 'Daniel V.', '1w', 4),\n"
                "('Artist', 'Brenda X.', '1w', 8),\n"
                "('Artist', 'Michael S.', '1w', 9),\n"
                "('Artist', 'Tanya E.', '1w', 2),\n"
                "('Artist', 'Sandra A.', '1w', 5); "
            ),
            "columns": ["Role", "Name", "Building", "Years_employed"],
            "rows": [
                ["Engineer", "Becky A.", "1e", 4],
                ["Engineer", "Dan B.", "1e", 2],
                ["Engineer", "Sharon F.", "1e", 6],
                ["Engineer", "Dan M.", "1e", 4],
                ["Engineer", "Malik S.", "1e", 1],
                ["Manager", "Yair L.", "1e", 10],
                ["Manager", "Katrina M.", "2w", 6],
                ["Manager", "Shirley P.", "2w", 3],
                ["Manager", "Brian M.", "1e", 9],
                ["Artist", "Daniel V.", "1w", 4],
                ["Artist", "Brenda X.", "1w", 8],
                ["Artist", "Michael S.", "1w", 9],
                ["Artist", "Tanya E.", "1w", 2],
                ["Artist", "Sandra A.", "1w", 5],
            ],
        },
        {
            "name": "Cities",
            "schema_sql": (
                "CREATE TABLE Cities (\n"
                "  City TEXT PRIMARY KEY,\n"
                "  Country TEXT NOT NULL,\n"
                "  Population INTEGER NOT NULL,\n"
                "  Latitude REAL NOT NULL,\n"
                "  Longitude REAL NOT NULL\n"
                ");"
            ),
            "insert_sql": (
                "INSERT INTO Cities (City, Country, Population, Latitude, Longitude) VALUES\n"
                "('Guadalajara', 'Mexico', 1500800, 20.659698, -103.349609),\n"
                "('Toronto', 'Canada', 2795060, 43.653226, -79.383184),\n"
                "('Houston', 'United States', 2195914, 29.760427, -95.369803),\n"
                "('New York', 'United States', 8405837, 40.712775, -74.005973),\n"
                "('Philadelphia', 'United States', 1553165, 39.952584, -75.165222),\n"
                "('Havana', 'Cuba', 2106146, 23.05407, -82.345189),\n"
                "('Mexico City', 'Mexico', 8851080, 19.432608, -99.133208),\n"
                "('Phoenix', 'United States', 1513367, 33.448377, -112.074037),\n"
                "('Los Angeles', 'United States', 3884307, 34.052234, -118.243685),\n"
                "('Ecatepec de Morelos', 'Mexico', 1656107, 19.601841, -99.050674),\n"
                "('Montreal', 'Canada', 1717767, 45.501689, -73.567256),\n"
                "('Chicago', 'United States', 2718782, 41.878114, -87.629798);"
            ),
            "columns": ["City", "Country", "Population", "Latitude", "Longitude"],
            "rows": [
                ["Guadalajara", "Mexico", 1500800, 20.659698, -103.349609],
                ["Toronto", "Canada", 2795060, 43.653226, -79.383184],
                ["Houston", "United States", 2195914, 29.760427, -95.369803],
                ["New York", "United States", 8405837, 40.712775, -74.005973],
                ["Philadelphia", "United States", 1553165, 39.952584, -75.165222],
                ["Havana", "Cuba", 2106146, 23.05407, -82.345189],
                ["Mexico City", "Mexico", 8851080, 19.432608, -99.133208],
                ["Phoenix", "United States", 1513367, 33.448377, -112.074037],
                ["Los Angeles", "United States", 3884307, 34.052234, -118.243685],
                ["Ecatepec de Morelos", "Mexico", 1656107, 19.601841, -99.050674],
                ["Montreal", "Canada", 1717767, 45.501689, -73.567256],
                ["Chicago", "United States", 2718782, 41.878114, -87.629798],
            ],
        },
    ]


def _load_fallback_sql_lessons() -> list[dict[str, Any]]:
    """Load SQLBolt lessons from local JSON file."""
    if SQLBOLT_JSON_PATH.exists():
        try:
            with open(SQLBOLT_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def fetch_all_courses(user_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch all 6 published courses, with lesson count and user progress."""
    track_lesson_counts: dict[str, int] = {
        "system-design": 30,
        "genai-system-design": 11,
        "ml-system-design": 11,
        "mobile-system-design": 11,
        "object-oriented-design": 14,
        "sql-course": len(_load_fallback_sql_lessons()) or 21,
    }

    user_completed_counts: dict[str, int] = {k: 0 for k in track_lesson_counts}

    # Fetch live lesson counts from Supabase if available
    try:
        supabase = get_supabase_client()
        lessons_data = (
            supabase.table("course_lessons")
            .select("track_id, step_no")
            .execute()
            .data
            or []
        )
        if lessons_data:
            counts: dict[str, int] = {}
            for l in lessons_data:
                t = l.get("track_id")
                if t:
                    counts[t] = counts.get(t, 0) + 1
            for t, c in counts.items():
                if t in track_lesson_counts:
                    track_lesson_counts[t] = c

        # If user is authenticated, query learning_track_progress
        if user_id:
            prog_data = (
                supabase.table("learning_track_progress")
                .select("track_id, step_no")
                .eq("user_id", user_id)
                .eq("completed", True)
                .execute()
                .data
                or []
            )
            for p in prog_data:
                t = p.get("track_id")
                if t in user_completed_counts:
                    user_completed_counts[t] += 1
    except Exception:
        pass

    # Merge with in-memory fallback for user progress
    if user_id:
        for c in COURSE_CATALOG:
            slug = c["slug"]
            key = f"{user_id}:{slug}"
            if key in _IN_MEMORY_USER_PROGRESS:
                user_completed_counts[slug] = max(
                    user_completed_counts.get(slug, 0),
                    len(_IN_MEMORY_USER_PROGRESS[key]),
                )

    result = []
    for c in COURSE_CATALOG:
        slug = c["slug"]
        total = track_lesson_counts.get(slug, 0)
        completed = min(user_completed_counts.get(slug, 0), total)
        pct = round((completed / total) * 100, 1) if total > 0 else 0.0

        result.append(
            {
                "id": c["id"],
                "slug": c["slug"],
                "title": c["title"],
                "description": c["description"],
                "total_lessons": total,
                "completed_lessons": completed,
                "progress_percentage": pct,
            }
        )

    return result


def fetch_course_by_slug(course_slug: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Fetch details of a single course with its ordered lesson list."""
    norm_slug = _normalize_track_id(course_slug)
    matched_meta = next((c for c in COURSE_CATALOG if c["slug"] == norm_slug), None)
    if not matched_meta:
        return None

    # Handle SQL course
    if norm_slug == "sql-course":
        sql_lessons = _load_fallback_sql_lessons()
        user_completed_slugs = (
            _IN_MEMORY_USER_PROGRESS.get(f"{user_id}:{norm_slug}", set())
            if user_id
            else set()
        )
        lesson_summaries = []
        completed_count = 0
        for idx, l in enumerate(sql_lessons, start=1):
            s = l["slug"]
            order_idx = l.get("order", idx)
            is_comp = s in user_completed_slugs
            if is_comp:
                completed_count += 1
            lesson_summaries.append(
                {
                    "id": f"sql-{order_idx}",
                    "slug": s,
                    "title": l["title"],
                    "order_index": order_idx,
                    "completed": is_comp,
                }
            )

        total_lessons = len(lesson_summaries)
        pct = round((completed_count / total_lessons) * 100, 1) if total_lessons > 0 else 0.0
        return {
            "id": matched_meta["id"],
            "slug": matched_meta["slug"],
            "title": matched_meta["title"],
            "description": matched_meta["description"],
            "total_lessons": total_lessons,
            "completed_lessons": completed_count,
            "progress_percentage": pct,
            "lessons": lesson_summaries,
        }

    # Handle System Design / GenAI / ML / Mobile / OOD tracks from Supabase
    completed_step_nos = set()
    if user_id:
        try:
            supabase = get_supabase_client()
            prog = (
                supabase.table("learning_track_progress")
                .select("step_no")
                .eq("user_id", user_id)
                .eq("track_id", norm_slug)
                .eq("completed", True)
                .execute()
                .data
                or []
            )
            completed_step_nos = {p["step_no"] for p in prog}
        except Exception:
            pass

        key = f"{user_id}:{norm_slug}"
        if key in _IN_MEMORY_USER_PROGRESS:
            for s in _IN_MEMORY_USER_PROGRESS[key]:
                m = re.search(r"(\d+)", s)
                if m:
                    completed_step_nos.add(int(m.group(1)))

    lesson_summaries = []
    completed_count = 0

    try:
        supabase = get_supabase_client()
        lessons_data = (
            supabase.table("course_lessons")
            .select("id, step_no, title")
            .eq("track_id", norm_slug)
            .order("step_no", desc=False)
            .execute()
            .data
            or []
        )

        for l in lessons_data:
            step_no = l.get("step_no", 1)
            is_comp = step_no in completed_step_nos
            if is_comp:
                completed_count += 1
            lesson_summaries.append(
                {
                    "id": str(l.get("id", f"{norm_slug}-{step_no}")),
                    "slug": f"step-{step_no}",
                    "title": l.get("title", f"Step {step_no}"),
                    "order_index": step_no,
                    "completed": is_comp,
                }
            )
    except Exception:
        pass

    if not lesson_summaries:
        # Fallback default placeholders
        default_count = 10
        for step_no in range(1, default_count + 1):
            is_comp = step_no in completed_step_nos
            if is_comp:
                completed_count += 1
            lesson_summaries.append(
                {
                    "id": f"{norm_slug}-{step_no}",
                    "slug": f"step-{step_no}",
                    "title": f"Step {step_no}: Lesson {step_no}",
                    "order_index": step_no,
                    "completed": is_comp,
                }
            )

    total_lessons = len(lesson_summaries)
    pct = round((completed_count / total_lessons) * 100, 1) if total_lessons > 0 else 0.0

    return {
        "id": matched_meta["id"],
        "slug": matched_meta["slug"],
        "title": matched_meta["title"],
        "description": matched_meta["description"],
        "total_lessons": total_lessons,
        "completed_lessons": completed_count,
        "progress_percentage": pct,
        "lessons": lesson_summaries,
    }


def fetch_lesson_detail(
    course_slug: str, lesson_slug: str, user_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Fetch full details of a specific lesson within a course."""
    norm_slug = _normalize_track_id(course_slug)

    # Handle SQL course
    if norm_slug == "sql-course":
        sql_lessons = _load_fallback_sql_lessons()
        target_idx = None
        target_lesson = None
        for idx, l in enumerate(sql_lessons):
            if l["slug"] == lesson_slug:
                target_idx = idx
                target_lesson = l
                break

        if target_lesson is None:
            return None

        prev_slug = sql_lessons[target_idx - 1]["slug"] if target_idx > 0 else None
        next_slug = (
            sql_lessons[target_idx + 1]["slug"]
            if target_idx < len(sql_lessons) - 1
            else None
        )

        completed = False
        if user_id:
            user_completed = _IN_MEMORY_USER_PROGRESS.get(f"{user_id}:{norm_slug}", set())
            completed = lesson_slug in user_completed

        return {
            "id": f"sql-{target_lesson.get('order', target_idx + 1)}",
            "course_slug": norm_slug,
            "slug": target_lesson["slug"],
            "title": target_lesson["title"],
            "order_index": target_lesson.get("order", target_idx + 1),
            "content_markdown": target_lesson.get("content_markdown", ""),
            "tasks": target_lesson.get("tasks", []),
            "completed": completed,
            "prev_lesson_slug": prev_slug,
            "next_lesson_slug": next_slug,
        }

    # Parse step_no from lesson_slug (e.g. 'step-4' -> 4)
    step_no = 1
    m = re.search(r"(\d+)", lesson_slug)
    if m:
        step_no = int(m.group(1))

    try:
        supabase = get_supabase_client()
        # Fetch current lesson
        row = (
            supabase.table("course_lessons")
            .select("id, track_id, step_no, title, html_content")
            .eq("track_id", norm_slug)
            .eq("step_no", step_no)
            .limit(1)
            .execute()
            .data
        )

        # Get total steps in this track to compute prev/next
        all_steps_data = (
            supabase.table("course_lessons")
            .select("step_no")
            .eq("track_id", norm_slug)
            .order("step_no", desc=False)
            .execute()
            .data
            or []
        )
        step_numbers = [s["step_no"] for s in all_steps_data]
    except Exception:
        row = []
        step_numbers = list(range(1, 31))

    if not row:
        # If not found by exact step_no, try fetching first available lesson
        try:
            supabase = get_supabase_client()
            row = (
                supabase.table("course_lessons")
                .select("id, track_id, step_no, title, html_content")
                .eq("track_id", norm_slug)
                .limit(1)
                .execute()
                .data
            )
        except Exception:
            row = []

    if not row:
        return None

    current = row[0]
    cur_step = current.get("step_no", step_no)

    prev_slug = f"step-{cur_step - 1}" if cur_step > 1 and (cur_step - 1 in step_numbers or not step_numbers) else None
    next_slug = f"step-{cur_step + 1}" if (cur_step + 1 in step_numbers) or (not step_numbers and cur_step < 30) else None

    # Check user completion
    completed = False
    if user_id:
        try:
            supabase = get_supabase_client()
            prog = (
                supabase.table("learning_track_progress")
                .select("completed")
                .eq("user_id", user_id)
                .eq("track_id", norm_slug)
                .eq("step_no", cur_step)
                .limit(1)
                .execute()
                .data
            )
            if prog:
                completed = bool(prog[0].get("completed", False))
        except Exception:
            pass

        key = f"{user_id}:{norm_slug}"
        if key in _IN_MEMORY_USER_PROGRESS and (f"step-{cur_step}" in _IN_MEMORY_USER_PROGRESS[key] or str(cur_step) in _IN_MEMORY_USER_PROGRESS[key]):
            completed = True

    return {
        "id": str(current.get("id", f"{norm_slug}-{cur_step}")),
        "course_slug": norm_slug,
        "slug": f"step-{cur_step}",
        "title": current.get("title", f"Step {cur_step}"),
        "order_index": cur_step,
        "content_markdown": current.get("html_content", ""),
        "tasks": [],
        "completed": completed,
        "prev_lesson_slug": prev_slug,
        "next_lesson_slug": next_slug,
    }


def record_lesson_completion(
    user_id: str, course_slug: str, lesson_slug: str, completed: bool = True
) -> dict[str, Any]:
    """Record completion of a lesson for an authenticated user."""
    norm_slug = _normalize_track_id(course_slug)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Track in in-memory progress cache
    key = f"{user_id}:{norm_slug}"
    if key not in _IN_MEMORY_USER_PROGRESS:
        _IN_MEMORY_USER_PROGRESS[key] = set()

    if completed:
        _IN_MEMORY_USER_PROGRESS[key].add(lesson_slug)
    else:
        _IN_MEMORY_USER_PROGRESS[key].discard(lesson_slug)

    # Persist in Supabase learning_track_progress
    step_no = 1
    m = re.search(r"(\d+)", lesson_slug)
    if m:
        step_no = int(m.group(1))

    try:
        supabase = get_supabase_client()
        supabase.table("learning_track_progress").upsert(
            {
                "user_id": user_id,
                "track_id": norm_slug,
                "step_no": step_no,
                "completed": completed,
                "updated_at": now_iso,
            },
            on_conflict="user_id,track_id,step_no",
        ).execute()
    except Exception:
        pass

    course_detail = fetch_course_by_slug(norm_slug, user_id=user_id)
    return {
        "success": True,
        "course_slug": norm_slug,
        "lesson_slug": lesson_slug,
        "completed": completed,
        "completed_at": now_iso,
        "course_progress": {
            "completed_lessons": course_detail["completed_lessons"] if course_detail else 0,
            "total_lessons": course_detail["total_lessons"] if course_detail else 0,
            "progress_percentage": course_detail["progress_percentage"] if course_detail else 0.0,
        },
    }


def fetch_course_user_progress(user_id: str, course_slug: str) -> Optional[dict[str, Any]]:
    """Get list of completed lesson slugs and progress percentage for a course."""
    norm_slug = _normalize_track_id(course_slug)
    course_detail = fetch_course_by_slug(norm_slug, user_id=user_id)
    if not course_detail:
        return None

    completed_slugs = [
        l["slug"] for l in course_detail.get("lessons", []) if l.get("completed")
    ]

    return {
        "course_slug": norm_slug,
        "completed_lessons": course_detail.get("completed_lessons", 0),
        "total_lessons": course_detail.get("total_lessons", 0),
        "progress_percentage": course_detail.get("progress_percentage", 0.0),
        "completed_lesson_slugs": completed_slugs,
    }

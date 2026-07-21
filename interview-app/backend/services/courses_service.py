"""Courses Service — business logic for courses, lessons, progress, and SQL seed data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.supabase_client import get_supabase_client

# Path to sqlbolt_courses.json
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
SQLBOLT_JSON_PATH = PROJECT_DIR / "scripts" / "sqlbolt_courses.json"

# In-memory user progress store for fallback / testing when Supabase table isn't accessible
_IN_MEMORY_USER_PROGRESS: dict[str, set[str]] = {}


def get_sql_seed_tables() -> list[dict[str, Any]]:
    """Return DDL statements and initial data for SQL practice tables (Movies, Boxoffice, Buildings, Employees, Cities)."""
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
                data = json.load(f)
                return data
        except Exception:
            pass
    return [
        {
            "slug": "select_queries_introduction",
            "order": 1,
            "title": "SQL Lesson 1: SELECT queries 101",
            "content_markdown": "# SQL Lesson 1: SELECT queries 101\n\nTo retrieve data from a SQL database, write a `SELECT` statement.\n\nUse `SELECT * FROM Movies;` to view all columns.",
            "tasks": [
                "Find the title of each film",
                "Find the director of each film",
                "Find the title and director of each film",
                "Find all the information about each film",
            ],
        }
    ]


def get_fallback_courses() -> list[dict[str, Any]]:
    """Return static catalog of published courses."""
    sql_lessons = _load_fallback_sql_lessons()
    return [
        {
            "id": "c0000000-0000-0000-0000-000000000001",
            "slug": "sql-course",
            "title": "SQL Practice Course",
            "description": "Master SQL queries step-by-step with interactive sql.js practice tables and exercises.",
            "lessons": sql_lessons,
        },
        {
            "id": "c0000000-0000-0000-0000-000000000002",
            "slug": "system-design",
            "title": "System Design Fundamentals",
            "description": "Master large-scale distributed system design principles and interview patterns.",
            "lessons": [
                {
                    "slug": "introduction-to-system-design",
                    "order": 1,
                    "title": "Introduction to System Design",
                    "content_markdown": "# System Design Introduction\n\nLearn core building blocks of scalable systems.",
                    "tasks": ["Review client-server model", "Understand DNS resolution"],
                },
                {
                    "slug": "load-balancing",
                    "order": 2,
                    "title": "Load Balancing Strategies",
                    "content_markdown": "# Load Balancing\n\nDistribute traffic efficiently across multiple servers.",
                    "tasks": ["Compare L4 vs L7 load balancers", "Study consistent hashing"],
                },
            ],
        },
        {
            "id": "c0000000-0000-0000-0000-000000000003",
            "slug": "object-oriented-design",
            "title": "Object-Oriented Design",
            "description": "Learn OOD patterns, class diagrams, and SOLID design principles.",
            "lessons": [
                {
                    "slug": "solid-principles",
                    "order": 1,
                    "title": "SOLID Design Principles",
                    "content_markdown": "# SOLID Principles\n\nFive core guidelines for maintainable object-oriented software.",
                    "tasks": ["Apply Single Responsibility Principle", "Implement Strategy Pattern"],
                }
            ],
        },
    ]


def fetch_all_courses(user_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch all published courses, with lesson count and user progress if user_id is provided."""
    try:
        supabase = get_supabase_client()
        db_courses = supabase.table("courses").select("*").execute().data
        if db_courses:
            result = []
            for course in db_courses:
                course_id = course["id"]
                lessons = (
                    supabase.table("course_lessons")
                    .select("id, slug")
                    .eq("course_id", course_id)
                    .execute()
                    .data
                    or []
                )
                total_lessons = len(lessons)
                completed_lessons = 0

                if user_id and total_lessons > 0:
                    lesson_ids = [l["id"] for l in lessons]
                    prog = (
                        supabase.table("user_lesson_progress")
                        .select("lesson_id")
                        .eq("user_id", user_id)
                        .eq("completed", True)
                        .in_("lesson_id", lesson_ids)
                        .execute()
                        .data
                        or []
                    )
                    completed_lessons = len(prog)

                pct = (
                    round((completed_lessons / total_lessons) * 100, 2)
                    if total_lessons > 0
                    else 0.0
                )
                result.append(
                    {
                        "id": course["id"],
                        "slug": course["slug"],
                        "title": course["title"],
                        "description": course.get("description", ""),
                        "total_lessons": total_lessons,
                        "completed_lessons": completed_lessons,
                        "progress_percentage": pct,
                    }
                )
            return result
    except Exception:
        pass

    # Fallback to static catalog if DB empty or unavailable
    fallback_courses = get_fallback_courses()
    result = []
    for c in fallback_courses:
        c_slug = c["slug"]
        lessons = c["lessons"]
        total_lessons = len(lessons)
        completed_lessons = 0

        if user_id and total_lessons > 0:
            user_completed_slugs = _IN_MEMORY_USER_PROGRESS.get(f"{user_id}:{c_slug}", set())
            completed_lessons = len(user_completed_slugs.intersection({l["slug"] for l in lessons}))

        pct = (
            round((completed_lessons / total_lessons) * 100, 2)
            if total_lessons > 0
            else 0.0
        )
        result.append(
            {
                "id": c["id"],
                "slug": c["slug"],
                "title": c["title"],
                "description": c["description"],
                "total_lessons": total_lessons,
                "completed_lessons": completed_lessons,
                "progress_percentage": pct,
            }
        )
    return result


def fetch_course_by_slug(course_slug: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Fetch details of a single course with ordered lesson list."""
    try:
        supabase = get_supabase_client()
        courses = (
            supabase.table("courses")
            .select("*")
            .eq("slug", course_slug)
            .limit(1)
            .execute()
            .data
        )
        if courses:
            course = courses[0]
            course_id = course["id"]
            lessons = (
                supabase.table("course_lessons")
                .select("id, slug, title, order_index")
                .eq("course_id", course_id)
                .order("order_index")
                .execute()
                .data
                or []
            )

            completed_lesson_ids = set()
            if user_id and lessons:
                prog = (
                    supabase.table("user_lesson_progress")
                    .select("lesson_id")
                    .eq("user_id", user_id)
                    .eq("completed", True)
                    .execute()
                    .data
                    or []
                )
                completed_lesson_ids = {p["lesson_id"] for p in prog}

            lesson_summaries = []
            completed_count = 0
            for l in lessons:
                is_completed = l["id"] in completed_lesson_ids
                if is_completed:
                    completed_count += 1
                lesson_summaries.append(
                    {
                        "id": str(l["id"]),
                        "slug": l["slug"],
                        "title": l["title"],
                        "order_index": l["order_index"],
                        "completed": is_completed,
                    }
                )

            total_lessons = len(lesson_summaries)
            pct = (
                round((completed_count / total_lessons) * 100, 2)
                if total_lessons > 0
                else 0.0
            )

            return {
                "id": str(course["id"]),
                "slug": course["slug"],
                "title": course["title"],
                "description": course.get("description", ""),
                "total_lessons": total_lessons,
                "completed_lessons": completed_count,
                "progress_percentage": pct,
                "lessons": lesson_summaries,
            }
    except Exception:
        pass

    # Fallback to static data
    fallback_courses = get_fallback_courses()
    for c in fallback_courses:
        if c["slug"] == course_slug:
            lessons = c["lessons"]
            user_completed_slugs = (
                _IN_MEMORY_USER_PROGRESS.get(f"{user_id}:{course_slug}", set())
                if user_id
                else set()
            )
            lesson_summaries = []
            completed_count = 0
            for idx, l in enumerate(lessons, start=1):
                slug = l["slug"]
                order_idx = l.get("order", idx)
                is_comp = slug in user_completed_slugs
                if is_comp:
                    completed_count += 1
                lesson_summaries.append(
                    {
                        "id": f"l-{course_slug}-{order_idx}",
                        "slug": slug,
                        "title": l["title"],
                        "order_index": order_idx,
                        "completed": is_comp,
                    }
                )

            total_lessons = len(lesson_summaries)
            pct = (
                round((completed_count / total_lessons) * 100, 2)
                if total_lessons > 0
                else 0.0
            )
            return {
                "id": c["id"],
                "slug": c["slug"],
                "title": c["title"],
                "description": c["description"],
                "total_lessons": total_lessons,
                "completed_lessons": completed_count,
                "progress_percentage": pct,
                "lessons": lesson_summaries,
            }

    return None


def fetch_lesson_detail(
    course_slug: str, lesson_slug: str, user_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Fetch full details of a specific lesson within a course."""
    try:
        supabase = get_supabase_client()
        courses = (
            supabase.table("courses")
            .select("id")
            .eq("slug", course_slug)
            .limit(1)
            .execute()
            .data
        )
        if courses:
            course_id = courses[0]["id"]
            lessons = (
                supabase.table("course_lessons")
                .select("id, slug, title, order_index, content_markdown")
                .eq("course_id", course_id)
                .order("order_index")
                .execute()
                .data
                or []
            )

            target_idx = None
            target_lesson = None
            for idx, l in enumerate(lessons):
                if l["slug"] == lesson_slug:
                    target_idx = idx
                    target_lesson = l
                    break

            if target_lesson is not None and target_idx is not None:
                # Fetch tasks
                tasks_data = (
                    supabase.table("lesson_tasks")
                    .select("description")
                    .eq("lesson_id", target_lesson["id"])
                    .order("order_index")
                    .execute()
                    .data
                    or []
                )
                tasks = [t["description"] for t in tasks_data]

                # Prev/next slugs
                prev_slug = lessons[target_idx - 1]["slug"] if target_idx > 0 else None
                next_slug = (
                    lessons[target_idx + 1]["slug"]
                    if target_idx < len(lessons) - 1
                    else None
                )

                # Check user completion
                completed = False
                if user_id:
                    prog = (
                        supabase.table("user_lesson_progress")
                        .select("completed")
                        .eq("user_id", user_id)
                        .eq("lesson_id", target_lesson["id"])
                        .limit(1)
                        .execute()
                        .data
                    )
                    if prog:
                        completed = bool(prog[0].get("completed", False))

                return {
                    "id": str(target_lesson["id"]),
                    "course_slug": course_slug,
                    "slug": target_lesson["slug"],
                    "title": target_lesson["title"],
                    "order_index": target_lesson["order_index"],
                    "content_markdown": target_lesson.get("content_markdown", ""),
                    "tasks": tasks,
                    "completed": completed,
                    "prev_lesson_slug": prev_slug,
                    "next_lesson_slug": next_slug,
                }
    except Exception:
        pass

    # Fallback to static catalog
    course_info = fetch_course_by_slug(course_slug, user_id=user_id)
    if not course_info:
        return None

    fallback_courses = get_fallback_courses()
    target_c = next((c for c in fallback_courses if c["slug"] == course_slug), None)
    if not target_c:
        return None

    lessons = target_c["lessons"]
    target_idx = None
    target_l = None
    for idx, l in enumerate(lessons):
        if l["slug"] == lesson_slug:
            target_idx = idx
            target_l = l
            break

    if target_l is None or target_idx is None:
        return None

    prev_slug = lessons[target_idx - 1]["slug"] if target_idx > 0 else None
    next_slug = (
        lessons[target_idx + 1]["slug"] if target_idx < len(lessons) - 1 else None
    )

    user_completed_slugs = (
        _IN_MEMORY_USER_PROGRESS.get(f"{user_id}:{course_slug}", set())
        if user_id
        else set()
    )
    completed = lesson_slug in user_completed_slugs

    return {
        "id": f"l-{course_slug}-{target_l.get('order', target_idx + 1)}",
        "course_slug": course_slug,
        "slug": target_l["slug"],
        "title": target_l["title"],
        "order_index": target_l.get("order", target_idx + 1),
        "content_markdown": target_l.get("content_markdown", ""),
        "tasks": target_l.get("tasks", []),
        "completed": completed,
        "prev_lesson_slug": prev_slug,
        "next_lesson_slug": next_slug,
    }


def record_lesson_completion(
    user_id: str, course_slug: str, lesson_slug: str, completed: bool = True
) -> dict[str, Any]:
    """Record completion of a lesson for an authenticated user."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        supabase = get_supabase_client()
        courses = (
            supabase.table("courses")
            .select("id")
            .eq("slug", course_slug)
            .limit(1)
            .execute()
            .data
        )
        if courses:
            course_id = courses[0]["id"]
            lessons = (
                supabase.table("course_lessons")
                .select("id")
                .eq("course_id", course_id)
                .eq("slug", lesson_slug)
                .limit(1)
                .execute()
                .data
            )
            if lessons:
                lesson_id = lessons[0]["id"]
                supabase.table("user_lesson_progress").upsert(
                    {
                        "user_id": user_id,
                        "lesson_id": lesson_id,
                        "completed": completed,
                        "completed_at": now_iso if completed else None,
                        "updated_at": now_iso,
                    },
                    on_conflict="user_id,lesson_id",
                ).execute()

                # Get updated course progress stats
                course_detail = fetch_course_by_slug(course_slug, user_id=user_id)
                return {
                    "success": True,
                    "course_slug": course_slug,
                    "lesson_slug": lesson_slug,
                    "completed": completed,
                    "completed_at": now_iso,
                    "course_progress": {
                        "completed_lessons": course_detail["completed_lessons"] if course_detail else 0,
                        "total_lessons": course_detail["total_lessons"] if course_detail else 0,
                        "progress_percentage": course_detail["progress_percentage"] if course_detail else 0.0,
                    },
                }
    except Exception:
        pass

    # In-memory fallback
    key = f"{user_id}:{course_slug}"
    if key not in _IN_MEMORY_USER_PROGRESS:
        _IN_MEMORY_USER_PROGRESS[key] = set()

    if completed:
        _IN_MEMORY_USER_PROGRESS[key].add(lesson_slug)
    else:
        _IN_MEMORY_USER_PROGRESS[key].discard(lesson_slug)

    course_detail = fetch_course_by_slug(course_slug, user_id=user_id)
    return {
        "success": True,
        "course_slug": course_slug,
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
    course_detail = fetch_course_by_slug(course_slug, user_id=user_id)
    if not course_detail:
        return None

    completed_slugs = [
        l["slug"] for l in course_detail["lessons"] if l["completed"]
    ]

    return {
        "course_slug": course_slug,
        "completed_lessons": course_detail["completed_lessons"],
        "total_lessons": course_detail["total_lessons"],
        "progress_percentage": course_detail["progress_percentage"],
        "completed_lesson_slugs": completed_slugs,
    }

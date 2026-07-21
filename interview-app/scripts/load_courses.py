import os
import json
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client


def load_courses():
    # 1. Resolve paths
    script_dir = Path(__file__).parent.resolve()
    app_dir = script_dir.parent.resolve()
    env_path = app_dir / ".env"
    json_path = script_dir / "sqlbolt_courses.json"

    # 2. Load environment variables from interview-app/.env
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables must be set in .env"
        )

    # 3. Create Supabase client
    supabase: Client = create_client(supabase_url, supabase_key)
    print(f"Connected to Supabase at: {supabase_url}")

    # 4. Read JSON
    if not json_path.exists():
        raise FileNotFoundError(f"Courses JSON file not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        lessons_data = json.load(f)

    print(f"Loaded {len(lessons_data)} lessons from {json_path.name}")

    # 5. Upsert default course: sql-tutorial
    course_payload = {
        "slug": "sql-tutorial",
        "title": "SQL Tutorial (SQLBolt)",
        "description": "Learn SQL interactively through hands-on queries and exercises.",
    }

    print("Upserting course 'sql-tutorial'...")
    supabase.table("courses").upsert(course_payload, on_conflict="slug").execute()

    # Query back course id to ensure accuracy
    course_query = (
        supabase.table("courses")
        .select("id")
        .eq("slug", "sql-tutorial")
        .execute()
    )
    if not course_query.data:
        raise RuntimeError("Failed to retrieve course ID for sql-tutorial")

    course_id = course_query.data[0]["id"]
    print(f"Course 'sql-tutorial' UUID: {course_id}")

    # 6. Process each lesson and its tasks
    total_lessons = 0
    total_tasks = 0

    for lesson in lessons_data:
        lesson_payload = {
            "course_id": course_id,
            "slug": lesson["slug"],
            "order_index": lesson["order"],
            "title": lesson["title"],
            "content_markdown": lesson.get("content_markdown", ""),
        }

        # Upsert lesson into course_lessons
        supabase.table("course_lessons").upsert(
            lesson_payload, on_conflict="course_id,slug"
        ).execute()

        # Retrieve lesson ID
        lesson_query = (
            supabase.table("course_lessons")
            .select("id")
            .eq("course_id", course_id)
            .eq("slug", lesson["slug"])
            .execute()
        )
        if not lesson_query.data:
            raise RuntimeError(
                f"Failed to retrieve lesson ID for slug: {lesson['slug']}"
            )

        lesson_id = lesson_query.data[0]["id"]
        total_lessons += 1

        # Delete existing tasks for this lesson to ensure clean idempotency
        supabase.table("lesson_tasks").delete().eq(
            "lesson_id", lesson_id
        ).execute()

        # Prepare tasks for insertion
        tasks = lesson.get("tasks", [])
        tasks_payload = [
            {
                "lesson_id": lesson_id,
                "order_index": idx + 1,
                "description": task_text,
            }
            for idx, task_text in enumerate(tasks)
        ]

        if tasks_payload:
            supabase.table("lesson_tasks").insert(tasks_payload).execute()
            total_tasks += len(tasks_payload)

    print(
        f"Successfully synced {total_lessons} lessons and {total_tasks} tasks for 'sql-tutorial'."
    )


if __name__ == "__main__":
    load_courses()

"""Courses API Router — endpoints for browsing courses, lessons, completing lessons, tracking progress, and obtaining SQL seed tables."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header

from models.schemas import (
    CourseSummary,
    CourseDetailResponse,
    LessonDetailResponse,
    LessonCompleteRequest,
    LessonCompleteResponse,
    CourseProgressResponse,
    SeedTablesResponse,
    SeedTableDefinition,
)
from routes.auth import get_current_user, get_optional_current_user
from services.courses_service import (
    fetch_all_courses,
    fetch_course_by_slug,
    fetch_lesson_detail,
    record_lesson_completion,
    fetch_course_user_progress,
    get_sql_seed_tables,
)

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseSummary])
def list_courses(user: Optional[dict] = Depends(get_optional_current_user)):
    """List all published courses with total lesson count and user progress if authenticated."""
    user_id = user["id"] if user else None
    courses = fetch_all_courses(user_id=user_id)
    return [CourseSummary(**c) for c in courses]


@router.get("/{course_slug}", response_model=CourseDetailResponse)
def get_course_detail(
    course_slug: str, user: Optional[dict] = Depends(get_optional_current_user)
):
    """Get details of a specific course and its ordered list of lessons."""
    user_id = user["id"] if user else None
    course = fetch_course_by_slug(course_slug, user_id=user_id)
    if not course:
        raise HTTPException(
            status_code=404, detail=f"Course '{course_slug}' not found."
        )
    return CourseDetailResponse(**course)


@router.get("/{course_slug}/seed-tables", response_model=SeedTablesResponse)
def get_course_seed_tables(course_slug: str):
    """Get client-side sql.js seed tables (DDLs, columns, rows) for interactive practice exercises."""
    tables_data = get_sql_seed_tables()
    table_defs = [SeedTableDefinition(**t) for t in tables_data]
    return SeedTablesResponse(course_slug=course_slug, tables=table_defs)


@router.get(
    "/{course_slug}/lessons/{lesson_slug}", response_model=LessonDetailResponse
)
def get_lesson_detail(
    course_slug: str,
    lesson_slug: str,
    user: Optional[dict] = Depends(get_optional_current_user),
):
    """Get full lesson details, content markdown, tasks, and next/prev lesson links."""
    user_id = user["id"] if user else None
    lesson = fetch_lesson_detail(course_slug, lesson_slug, user_id=user_id)
    if not lesson:
        raise HTTPException(
            status_code=404,
            detail=f"Lesson '{lesson_slug}' in course '{course_slug}' not found.",
        )
    return LessonDetailResponse(**lesson)


@router.post(
    "/{course_slug}/lessons/{lesson_slug}/complete",
    response_model=LessonCompleteResponse,
)
def complete_lesson(
    course_slug: str,
    lesson_slug: str,
    payload: Optional[LessonCompleteRequest] = None,
    user: dict = Depends(get_current_user),
):
    """Record completion of a lesson for an authenticated user."""
    # Verify course and lesson exist first
    lesson = fetch_lesson_detail(course_slug, lesson_slug, user_id=user["id"])
    if not lesson:
        raise HTTPException(
            status_code=404,
            detail=f"Lesson '{lesson_slug}' in course '{course_slug}' not found.",
        )

    is_completed = payload.completed if payload else True
    res = record_lesson_completion(
        user_id=user["id"],
        course_slug=course_slug,
        lesson_slug=lesson_slug,
        completed=is_completed,
    )
    return LessonCompleteResponse(**res)


@router.get("/{course_slug}/progress", response_model=CourseProgressResponse)
def get_course_progress(course_slug: str, user: dict = Depends(get_current_user)):
    """Get user progress (completed lesson slugs, percentage) for a course."""
    prog = fetch_course_user_progress(user_id=user["id"], course_slug=course_slug)
    if not prog:
        raise HTTPException(
            status_code=404, detail=f"Course '{course_slug}' not found."
        )
    return CourseProgressResponse(**prog)

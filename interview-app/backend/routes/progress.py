"""Progress routes — track user question progress in Supabase."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from models.schemas import (
    ProgressUpdateRequest,
    UserProgressResponse,
    ProgressStats,
    ProgressEntry,
    ProgressStatusResponse,
    TopicProgressEntry,
)
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client
from services.questions_service import (
    find_qnum_by_question_id,
    get_question_summary_by_qnum,
    get_all_questions_catalog,
)

router = APIRouter(prefix="/progress", tags=["progress"])

def _coerce_state_from_payload(payload: ProgressUpdateRequest, current_is_solved: bool, current_revisit: bool) -> tuple[bool, bool]:
    is_solved = current_is_solved
    revisit = current_revisit

    if payload.is_solved is not None:
        is_solved = bool(payload.is_solved)

    if payload.revisit is not None:
        revisit = bool(payload.revisit)

    return is_solved, revisit


@router.post("/update")
def update_progress(payload: ProgressUpdateRequest, user: dict = Depends(get_current_user)):
    """Update question progress using is_solved/revisit values."""
    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    qnum = payload.qnum
    if qnum is None and payload.question_id:
        qnum = find_qnum_by_question_id(payload.question_id)

    if qnum is None:
        raise HTTPException(
            status_code=422,
            detail="Provide either a valid qnum or a resolvable question_id.",
        )

    if payload.is_solved is None and payload.revisit is None:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one of: is_solved, revisit.",
        )

    try:
        existing_rows = (
            supabase.table("user_progress")
            .select("is_solved,is_revisit")
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .limit(1)
            .execute()
        ).data or []

        existing = existing_rows[0] if existing_rows else {}
        current_is_solved = bool(existing.get("is_solved", False))
        current_revisit = bool(existing.get("is_revisit", False))

        next_is_solved, next_revisit = _coerce_state_from_payload(payload, current_is_solved, current_revisit)

        supabase.table("user_progress").upsert(
            {
                "user_id": user["id"],
                "qnum": qnum,
                "is_solved": next_is_solved,
                "is_revisit": next_revisit,
                "updated_at": now,
            },
            on_conflict="user_id,qnum",
        ).execute()

        # Also add to practice_history
        supabase.table("practice_history").insert(
            {
                "user_id": user["id"],
                "qnum": qnum,
            }
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {
        "success": True,
        "is_solved": next_is_solved,
        "revisit": next_revisit,
        "qnum": qnum,
    }


@router.get("/user", response_model=UserProgressResponse)
def get_user_progress(user: dict = Depends(get_current_user)):
    """Return aggregated progress stats and recent progress entries."""
    supabase = get_supabase_client()

    try:
        # Get all progress entries for this user
        result = (
            supabase.table("user_progress")
            .select("*")
            .eq("user_id", user["id"])
            .order("updated_at", desc=True)
            .execute()
        )
        entries = result.data or []
    except Exception:
        entries = []

    summary_cache: dict[int, dict] = {}

    def _get_summary(qnum: int) -> dict:
        safe_qnum = int(qnum or 0)
        if safe_qnum <= 0:
            return {}
        if safe_qnum not in summary_cache:
            summary_cache[safe_qnum] = get_question_summary_by_qnum(safe_qnum)
        return summary_cache[safe_qnum]

    easy_attempted = 0
    medium_attempted = 0
    hard_attempted = 0
    easy_solved = 0
    medium_solved = 0
    hard_solved = 0

    for entry in entries:
        qnum = int(entry.get("qnum", 0) or 0)
        difficulty = str(_get_summary(qnum).get("difficulty", "")).strip().lower()
        is_solved = bool(entry.get("is_solved", False))

        if difficulty == "easy":
            easy_attempted += 1
            if is_solved:
                easy_solved += 1
        elif difficulty == "medium":
            medium_attempted += 1
            if is_solved:
                medium_solved += 1
        elif difficulty == "hard":
            hard_attempted += 1
            if is_solved:
                hard_solved += 1

    solved_qnums = {
        int(entry.get("qnum", 0) or 0)
        for entry in entries
        if bool(entry.get("is_solved", False)) and int(entry.get("qnum", 0) or 0) > 0
    }

    try:
        catalog_rows = get_all_questions_catalog()
    except Exception:
        catalog_rows = []

    easy_total_questions = 0
    medium_total_questions = 0
    hard_total_questions = 0
    easy_solved_total_questions = 0
    medium_solved_total_questions = 0
    hard_solved_total_questions = 0

    topic_map: dict[str, dict] = {}

    for question in catalog_rows:
        qnum = int(question.get("qnum", 0) or 0)
        related_qnums = [
            int(v)
            for v in (question.get("related_qnums") or [])
            if int(v or 0) > 0
        ]
        candidate_qnums = related_qnums if related_qnums else ([qnum] if qnum > 0 else [])
        is_solved_catalog = any(candidate in solved_qnums for candidate in candidate_qnums)

        difficulty = str(question.get("difficulty", "")).strip().lower()
        if difficulty == "easy":
            easy_total_questions += 1
            if is_solved_catalog:
                easy_solved_total_questions += 1
        elif difficulty == "medium":
            medium_total_questions += 1
            if is_solved_catalog:
                medium_solved_total_questions += 1
        elif difficulty == "hard":
            hard_total_questions += 1
            if is_solved_catalog:
                hard_solved_total_questions += 1

        topic_tags = [
            str(value).strip()
            for value in (question.get("topic_tags") or [])
            if str(value).strip()
        ]
        topic_pairs = {(tag.lower(), tag) for tag in topic_tags}

        for topic_key, topic_label in topic_pairs:
            bucket = topic_map.setdefault(
                topic_key,
                {
                    "topic_key": topic_key,
                    "topic": topic_label,
                    "total_questions": 0,
                    "solved_questions": 0,
                    "easy_total_questions": 0,
                    "medium_total_questions": 0,
                    "hard_total_questions": 0,
                    "easy_solved_questions": 0,
                    "medium_solved_questions": 0,
                    "hard_solved_questions": 0,
                },
            )

            bucket["total_questions"] += 1
            if is_solved_catalog:
                bucket["solved_questions"] += 1

            if difficulty == "easy":
                bucket["easy_total_questions"] += 1
                if is_solved_catalog:
                    bucket["easy_solved_questions"] += 1
            elif difficulty == "medium":
                bucket["medium_total_questions"] += 1
                if is_solved_catalog:
                    bucket["medium_solved_questions"] += 1
            elif difficulty == "hard":
                bucket["hard_total_questions"] += 1
                if is_solved_catalog:
                    bucket["hard_solved_questions"] += 1

    topic_breakdown = [
        TopicProgressEntry(**topic_data)
        for topic_data in sorted(
            topic_map.values(),
            key=lambda item: (-int(item.get("total_questions", 0)), str(item.get("topic", "")).lower()),
        )
    ]

    total_questions = easy_total_questions + medium_total_questions + hard_total_questions
    solved_total_questions = easy_solved_total_questions + medium_solved_total_questions + hard_solved_total_questions

    # Calculate stats
    stats = ProgressStats(
        total_attempted=len(entries),
        solved_count=sum(1 for e in entries if bool(e.get("is_solved", False))),
        unsolved_count=sum(1 for e in entries if not bool(e.get("is_solved", False))),
        revisit_count=sum(
            1
            for e in entries
            if bool(e.get("is_revisit", False))
        ),
        easy_attempted=easy_attempted,
        medium_attempted=medium_attempted,
        hard_attempted=hard_attempted,
        easy_solved=easy_solved,
        medium_solved=medium_solved,
        hard_solved=hard_solved,
        total_questions=total_questions,
        solved_total_questions=solved_total_questions,
        easy_total_questions=easy_total_questions,
        medium_total_questions=medium_total_questions,
        hard_total_questions=hard_total_questions,
        easy_solved_total_questions=easy_solved_total_questions,
        medium_solved_total_questions=medium_solved_total_questions,
        hard_solved_total_questions=hard_solved_total_questions,
    )

    # Recent entries (last 20)
    recent: list[ProgressEntry] = []
    for entry in entries[:20]:
        qnum = int(entry.get("qnum", 0) or 0)
        summary = _get_summary(qnum)
        recent.append(
            ProgressEntry(
                qnum=qnum,
                question_id=summary.get("question_id", ""),
                question_title=summary.get("question_title", f"Question #{qnum}"),
                company=summary.get("company", ""),
                difficulty=summary.get("difficulty", ""),
                is_solved=bool(entry.get("is_solved", False)),
                revisit=bool(entry.get("is_revisit", False)),
                updated_at=entry.get("updated_at", ""),
            )
        )

    return UserProgressResponse(stats=stats, recent=recent, topic_breakdown=topic_breakdown)


@router.get("/status/{qnum}", response_model=ProgressStatusResponse)
def get_question_progress_status(qnum: int, user: dict = Depends(get_current_user)):
    """Return saved progress state for one question, or null/false when not set."""
    if qnum <= 0:
        raise HTTPException(status_code=422, detail="qnum must be greater than 0")

    supabase = get_supabase_client()
    try:
        rows = (
            supabase.table("user_progress")
            .select("is_solved,is_revisit")
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .limit(1)
            .execute()
        ).data or []
        is_solved = bool(rows[0].get("is_solved", False)) if rows else None
        revisit = bool(rows[0].get("is_revisit", False)) if rows else False
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return ProgressStatusResponse(qnum=qnum, is_solved=is_solved, revisit=revisit)


@router.delete("/{qnum}")
def clear_question_progress(qnum: int, user: dict = Depends(get_current_user)):
    """Clear saved progress for a question (manual not-solved/reset)."""
    if qnum <= 0:
        raise HTTPException(status_code=422, detail="qnum must be greater than 0")

    supabase = get_supabase_client()
    try:
        (
            supabase.table("user_progress")
            .delete()
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True, "qnum": qnum}

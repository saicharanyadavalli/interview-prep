"""Progress routes — track user question progress in Supabase."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from models.schemas import (
    ProgressUpdateRequest,
    UserProgressResponse,
    ProgressStats,
    ProgressEntry,
    ProgressStatusResponse,
    TopicProgressEntry,
)
import logging
from routes.auth import get_current_user, get_optional_current_user
from services import rds_client

logger = logging.getLogger(__name__)
from services.questions_service import (
    find_qnum_by_question_id,
    get_question_summary_by_qnum,
    get_all_questions_catalog,
)
from services.system_design_course import is_reserved_learning_track_qnum

router = APIRouter(prefix="/progress", tags=["progress"])

def _calculate_streak(entries: list[dict]) -> int:
    """Calculate user practice streak in consecutive days."""
    unique_days = set()
    for e in entries:
        ts = e.get("updated_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            unique_days.add(dt.date())
        except Exception:
            pass

    if not unique_days:
        return 0

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    if today in unique_days:
        cursor = today
    elif yesterday in unique_days:
        cursor = yesterday
    else:
        return 0

    streak = 0
    while cursor in unique_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


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
    """Update question progress in RDS using is_solved/revisit values."""
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
        existing = rds_client.query(
            "SELECT is_solved, is_revisit FROM user_progress WHERE user_id = %s AND qnum = %s LIMIT 1;",
            (user["id"], qnum),
            fetch="one",
        ) or {}

        current_is_solved = bool(existing.get("is_solved", False))
        current_revisit = bool(existing.get("is_revisit", False))

        next_is_solved, next_revisit = _coerce_state_from_payload(payload, current_is_solved, current_revisit)

        rds_client.mutate(
            """
            INSERT INTO user_progress (user_id, qnum, is_solved, is_revisit, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (user_id, qnum) DO UPDATE
            SET is_solved = EXCLUDED.is_solved,
                is_revisit = EXCLUDED.is_revisit,
                updated_at = now();
            """,
            (user["id"], qnum, next_is_solved, next_revisit),
        )

        # Also add to practice_history
        rds_client.mutate(
            "INSERT INTO practice_history (user_id, qnum, practiced_at) VALUES (%s, %s, now());",
            (user["id"], qnum),
        )
    except Exception as exc:
        logger.error("update_progress RDS error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {
        "success": True,
        "is_solved": next_is_solved,
        "revisit": next_revisit,
        "qnum": qnum,
    }


@router.get("/user", response_model=UserProgressResponse)
def get_user_progress(summary_only: bool = False, user: dict | None = Depends(get_optional_current_user)):
    """Return aggregated progress stats and recent progress entries."""
    if not user:
        return UserProgressResponse(
            stats=ProgressStats(
                total_attempted=0,
                solved_count=0,
                unsolved_count=0,
                revisit_count=0,
                current_streak=0,
                easy_attempted=0,
                medium_attempted=0,
                hard_attempted=0,
                easy_solved=0,
                medium_solved=0,
                hard_solved=0,
                total_questions=0,
                solved_total_questions=0,
                easy_total_questions=0,
                medium_total_questions=0,
                hard_total_questions=0,
                easy_solved_total_questions=0,
                medium_solved_total_questions=0,
                hard_solved_total_questions=0,
            ),
            recent=[],
            topic_breakdown=[],
        )

    try:
        # Get all progress entries for this user from RDS
        raw_entries = rds_client.query(
            """
            SELECT id, user_id, qnum, is_solved, is_revisit, updated_at
            FROM user_progress
            WHERE user_id = %s
            ORDER BY updated_at DESC;
            """,
            (user["id"],),
        ) or []
        entries = [
            e for e in raw_entries
            if not is_reserved_learning_track_qnum(int(e.get("qnum", 0) or 0))
        ]
    except Exception as exc:
        logger.error("get_user_progress RDS error: %s", exc)
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

    if summary_only:
        stats = ProgressStats(
            total_attempted=len(entries),
            solved_count=len(solved_qnums),
            unsolved_count=len(entries) - len(solved_qnums),
            revisit_count=sum(1 for e in entries if bool(e.get("is_revisit", False))),
            current_streak=_calculate_streak(entries),
            easy_attempted=easy_attempted,
            medium_attempted=medium_attempted,
            hard_attempted=hard_attempted,
            easy_solved=easy_solved,
            medium_solved=medium_solved,
            hard_solved=hard_solved,
            total_questions=0,
            solved_total_questions=0,
            easy_total_questions=0,
            medium_total_questions=0,
            hard_total_questions=0,
            easy_solved_total_questions=0,
            medium_solved_total_questions=0,
            hard_solved_total_questions=0,
        )
        
        recent_entries = []
        for entry in entries[:20]:
            qnum = int(entry.get("qnum", 0) or 0)
            summary = _get_summary(qnum)
            recent_entries.append(
                ProgressEntry(
                    qnum=qnum,
                    question_id=summary.get("question_id", ""),
                    question_title=summary.get("question_title", f"Question #{qnum}"),
                    company=summary.get("company", ""),
                    difficulty=summary.get("difficulty", ""),
                    is_solved=bool(entry.get("is_solved", False)),
                    revisit=bool(entry.get("is_revisit", False)),
                    updated_at=str(entry.get("updated_at", "")),
                )
            )
            
        return UserProgressResponse(
            stats=stats,
            recent=recent_entries,
            topic_breakdown=[],
        )

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

    solved_topic_keys: set[str] = set()
    prepared_questions: list[dict] = []

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

        if is_solved_catalog:
            solved_topic_keys.update({topic_key for topic_key, _ in topic_pairs})

        prepared_questions.append(
            {
                "difficulty": difficulty,
                "is_solved": is_solved_catalog,
                "topic_pairs": topic_pairs,
            }
        )

    topic_map: dict[str, dict] = {}

    for question in prepared_questions:
        difficulty = str(question.get("difficulty", "")).strip().lower()
        is_solved_catalog = bool(question.get("is_solved", False))
        topic_pairs = question.get("topic_pairs") or set()

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
        current_streak=_calculate_streak(entries),
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
def get_question_progress_status(qnum: int, user: dict | None = Depends(get_optional_current_user)):
    """Return saved progress state for one question from RDS."""
    if qnum <= 0:
        raise HTTPException(status_code=422, detail="qnum must be greater than 0")

    if not user:
        return ProgressStatusResponse(qnum=qnum, is_solved=None, revisit=False)

    try:
        row = rds_client.query(
            "SELECT is_solved, is_revisit FROM user_progress WHERE user_id = %s AND qnum = %s LIMIT 1;",
            (user["id"], qnum),
            fetch="one",
        )
        is_solved = bool(row.get("is_solved", False)) if row else None
        revisit = bool(row.get("is_revisit", False)) if row else False
    except Exception as exc:
        logger.error("get_question_progress_status RDS error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return ProgressStatusResponse(qnum=qnum, is_solved=is_solved, revisit=revisit)


@router.delete("/{qnum}")
def clear_question_progress(qnum: int, user: dict = Depends(get_current_user)):
    """Clear saved progress for a question in RDS (manual not-solved/reset)."""
    if qnum <= 0:
        raise HTTPException(status_code=422, detail="qnum must be greater than 0")

    try:
        rds_client.mutate(
            "DELETE FROM user_progress WHERE user_id = %s AND qnum = %s;",
            (user["id"], qnum),
        )
    except Exception as exc:
        logger.error("clear_question_progress RDS error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True, "qnum": qnum}

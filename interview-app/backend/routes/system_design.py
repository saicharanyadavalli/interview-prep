"""System design learning-track routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from models.schemas import (
    SystemDesignProgressResponse,
    SystemDesignStepProgress,
    SystemDesignProgressUpdateRequest,
)
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client
from services.system_design_course import (
    SYSTEM_DESIGN_STEP_COUNT,
    SYSTEM_DESIGN_QNUM_BASE,
    step_to_qnum,
    qnum_to_step,
    load_system_design_titles,
)

router = APIRouter(prefix="/system-design", tags=["system-design"])


@router.get("/progress", response_model=SystemDesignProgressResponse)
def get_system_design_progress(user: dict = Depends(get_current_user)):
    """Return per-step completion state for 30 system-design lessons."""
    supabase = get_supabase_client()

    try:
        rows = (
            supabase.table("user_progress")
            .select("qnum,is_solved,updated_at")
            .eq("user_id", user["id"])
            .gte("qnum", SYSTEM_DESIGN_QNUM_BASE + 1)
            .lte("qnum", SYSTEM_DESIGN_QNUM_BASE + SYSTEM_DESIGN_STEP_COUNT)
            .order("qnum")
            .execute()
        ).data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    by_step: dict[int, dict] = {}
    for row in rows:
        step_no = qnum_to_step(int(row.get("qnum", 0) or 0))
        if not step_no:
            continue
        by_step[step_no] = row

    titles = load_system_design_titles()
    steps: list[SystemDesignStepProgress] = []
    completed_steps = 0

    for step_no in range(1, SYSTEM_DESIGN_STEP_COUNT + 1):
        row = by_step.get(step_no, {})
        completed = bool(row.get("is_solved", False))
        if completed:
            completed_steps += 1

        steps.append(
            SystemDesignStepProgress(
                step_no=step_no,
                title=titles.get(step_no, f"Step {step_no}"),
                completed=completed,
                updated_at=row.get("updated_at"),
            )
        )

    completion_percent = int(round((completed_steps / SYSTEM_DESIGN_STEP_COUNT) * 100))
    return SystemDesignProgressResponse(
        total_steps=SYSTEM_DESIGN_STEP_COUNT,
        completed_steps=completed_steps,
        completion_percent=completion_percent,
        steps=steps,
    )


@router.post("/progress", response_model=SystemDesignStepProgress)
def update_system_design_progress(
    payload: SystemDesignProgressUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Mark a system-design lesson step as completed or not completed."""
    step_no = int(payload.step_no or 0)
    if step_no < 1 or step_no > SYSTEM_DESIGN_STEP_COUNT:
        raise HTTPException(
            status_code=422,
            detail=f"step_no must be between 1 and {SYSTEM_DESIGN_STEP_COUNT}",
        )

    qnum = step_to_qnum(step_no)
    now = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase_client()

    try:
        supabase.table("user_progress").upsert(
            {
                "user_id": user["id"],
                "qnum": qnum,
                "is_solved": bool(payload.completed),
                "is_revisit": False,
                "updated_at": now,
            },
            on_conflict="user_id,qnum",
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    titles = load_system_design_titles()
    return SystemDesignStepProgress(
        step_no=step_no,
        title=titles.get(step_no, f"Step {step_no}"),
        completed=bool(payload.completed),
        updated_at=now,
    )

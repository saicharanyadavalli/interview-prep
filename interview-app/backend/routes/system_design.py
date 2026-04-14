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
from services.system_design_course import SYSTEM_DESIGN_STEP_COUNT, load_system_design_titles

router = APIRouter(prefix="/system-design", tags=["system-design"])


def _normalize_completed_steps(raw_steps: list | None) -> list[int]:
    """Return unique, sorted, in-range step numbers."""
    seen: set[int] = set()
    normalized: list[int] = []

    for raw in (raw_steps or []):
        try:
            step_no = int(raw)
        except Exception:
            continue

        if step_no < 1 or step_no > SYSTEM_DESIGN_STEP_COUNT:
            continue
        if step_no in seen:
            continue

        seen.add(step_no)
        normalized.append(step_no)

    normalized.sort()
    return normalized


def _ensure_user_profile_row(supabase, user: dict) -> None:
    """Ensure one user_profiles row exists so array progress can be stored."""
    rows = (
        supabase.table("user_profiles")
        .select("id")
        .eq("id", user["id"])
        .limit(1)
        .execute()
    ).data or []

    if rows:
        return

    supabase.table("user_profiles").insert(
        {
            "id": user["id"],
            "email": user.get("email", ""),
            "name": user.get("name", "") or "",
            "avatar_url": user.get("avatar_url", "") or "",
        }
    ).execute()


@router.get("/progress", response_model=SystemDesignProgressResponse)
def get_system_design_progress(user: dict = Depends(get_current_user)):
    """Return per-step completion state for 30 system-design lessons."""
    supabase = get_supabase_client()

    try:
        _ensure_user_profile_row(supabase, user)
        rows = (
            supabase.table("user_profiles")
            .select("system_design_completed_steps")
            .eq("id", user["id"])
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    row = rows[0] if rows else {}
    completed_steps = _normalize_completed_steps(row.get("system_design_completed_steps"))
    completed_lookup = set(completed_steps)

    titles = load_system_design_titles()
    steps: list[SystemDesignStepProgress] = []
    completed_count = 0

    for step_no in range(1, SYSTEM_DESIGN_STEP_COUNT + 1):
        completed = step_no in completed_lookup
        if completed:
            completed_count += 1

        steps.append(
            SystemDesignStepProgress(
                step_no=step_no,
                title=titles.get(step_no, f"Step {step_no}"),
                completed=completed,
                updated_at=None,
            )
        )

    completion_percent = int(round((completed_count / SYSTEM_DESIGN_STEP_COUNT) * 100))
    return SystemDesignProgressResponse(
        total_steps=SYSTEM_DESIGN_STEP_COUNT,
        completed_steps=completed_count,
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

    now = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase_client()

    try:
        _ensure_user_profile_row(supabase, user)

        rows = (
            supabase.table("user_profiles")
            .select("system_design_completed_steps")
            .eq("id", user["id"])
            .limit(1)
            .execute()
        ).data or []

        row = rows[0] if rows else {}
        current_steps = _normalize_completed_steps(row.get("system_design_completed_steps"))
        next_steps_set = set(current_steps)

        if bool(payload.completed):
            next_steps_set.add(step_no)
        else:
            next_steps_set.discard(step_no)

        next_steps = sorted(next_steps_set)

        supabase.table("user_profiles").update(
            {
                "system_design_completed_steps": next_steps,
                "updated_at": now,
            }
        ).eq("id", user["id"]).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    titles = load_system_design_titles()
    return SystemDesignStepProgress(
        step_no=step_no,
        title=titles.get(step_no, f"Step {step_no}"),
        completed=bool(payload.completed),
        updated_at=now,
    )

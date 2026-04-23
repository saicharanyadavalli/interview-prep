"""Learning-track progress routes.

Serves all 5 learning tracks:
  - system-design
  - object-oriented-design
  - mobile-system-design
  - ml-system-design
  - genai-system-design

Progress is stored in the `learning_track_progress` table (separate from
`user_progress` which is exclusively for DSA questions).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from models.schemas import (
    LearningTrackMeta,
    LearningTrackProgressResponse,
    LearningTrackProgressUpdateRequest,
    LearningTrackStepProgress,
    LearningTracksResponse,
    SystemDesignProgressResponse,
    SystemDesignStepProgress,
    SystemDesignProgressUpdateRequest,
)
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client
from services.system_design_course import (
    get_learning_track_config,
    get_learning_tracks,
    load_learning_track_titles,
)

router = APIRouter(tags=["learning-tracks"])


# ── helpers ──────────────────────────────────────────────────────────

def _build_learning_track_progress(track_id: str, user: dict) -> LearningTrackProgressResponse:
    """Fetch all step rows for *track_id* from ``learning_track_progress``
    and merge with titles from the course-index JSON."""

    config = get_learning_track_config(track_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Unknown learning track: {track_id}")

    supabase = get_supabase_client()

    try:
        rows = (
            supabase.table("learning_track_progress")
            .select("step_no,completed,updated_at")
            .eq("user_id", user["id"])
            .eq("track_id", track_id)
            .order("step_no")
            .execute()
        ).data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    # Build lookup: step_no → row
    by_step: dict[int, dict] = {}
    for row in rows:
        step_no = int(row.get("step_no", 0) or 0)
        if step_no > 0:
            by_step[step_no] = row

    titles = load_learning_track_titles(track_id)
    steps: list[LearningTrackStepProgress] = []
    completed_steps = 0

    for step_no in range(1, config.step_count + 1):
        row = by_step.get(step_no, {})
        completed = bool(row.get("completed", False))
        if completed:
            completed_steps += 1

        steps.append(
            LearningTrackStepProgress(
                step_no=step_no,
                title=titles.get(step_no, f"Chapter {step_no}"),
                completed=completed,
                updated_at=row.get("updated_at"),
            )
        )

    completion_percent = int(round((completed_steps / config.step_count) * 100)) if config.step_count else 0
    return LearningTrackProgressResponse(
        track_id=track_id,
        total_steps=config.step_count,
        completed_steps=completed_steps,
        completion_percent=completion_percent,
        steps=steps,
    )


def _update_learning_track_progress(
    track_id: str,
    payload: LearningTrackProgressUpdateRequest,
    user: dict,
) -> LearningTrackStepProgress:
    """Upsert a single step's completion state into ``learning_track_progress``."""

    config = get_learning_track_config(track_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Unknown learning track: {track_id}")

    step_no = int(payload.step_no or 0)
    if step_no < 1 or step_no > config.step_count:
        raise HTTPException(
            status_code=422,
            detail=f"step_no must be between 1 and {config.step_count}",
        )

    now = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase_client()

    try:
        supabase.table("learning_track_progress").upsert(
            {
                "user_id": user["id"],
                "track_id": track_id,
                "step_no": step_no,
                "completed": bool(payload.completed),
                "updated_at": now,
            },
            on_conflict="user_id,track_id,step_no",
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    titles = load_learning_track_titles(track_id)
    return LearningTrackStepProgress(
        step_no=step_no,
        title=titles.get(step_no, f"Chapter {step_no}"),
        completed=bool(payload.completed),
        updated_at=now,
    )


# ── routes ───────────────────────────────────────────────────────────

@router.get("/learning-tracks", response_model=LearningTracksResponse)
def get_learning_tracks_meta(_: dict = Depends(get_current_user)):
    """Return all configured learning-track metadata."""
    tracks = [
        LearningTrackMeta(
            track_id=config.track_id,
            display_name=config.display_name,
            step_count=config.step_count,
            qnum_base=config.qnum_base,
            assets_slug=config.assets_slug,
        )
        for config in get_learning_tracks()
    ]
    return LearningTracksResponse(tracks=tracks)


@router.get("/learning-tracks/{track_id}/progress", response_model=LearningTrackProgressResponse)
def get_learning_track_progress(track_id: str, user: dict = Depends(get_current_user)):
    """Return per-step completion state for one learning track."""
    return _build_learning_track_progress(track_id, user)


@router.post("/learning-tracks/{track_id}/progress", response_model=LearningTrackStepProgress)
def update_learning_track_progress(
    track_id: str,
    payload: LearningTrackProgressUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update completion state for one learning-track step."""
    return _update_learning_track_progress(track_id, payload, user)


# ── legacy system-design endpoints (backward compat) ─────────────

@router.get("/system-design/progress", response_model=SystemDesignProgressResponse)
def get_system_design_progress_legacy(user: dict = Depends(get_current_user)):
    """Compatibility endpoint for older frontend versions."""
    progress = _build_learning_track_progress("system-design", user)
    return SystemDesignProgressResponse(
        total_steps=progress.total_steps,
        completed_steps=progress.completed_steps,
        completion_percent=progress.completion_percent,
        steps=[
            SystemDesignStepProgress(
                step_no=step.step_no,
                title=step.title,
                completed=step.completed,
                updated_at=step.updated_at,
            )
            for step in progress.steps
        ],
    )


@router.post("/system-design/progress", response_model=SystemDesignStepProgress)
def update_system_design_progress_legacy(
    payload: SystemDesignProgressUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Compatibility endpoint for older frontend versions."""
    result = _update_learning_track_progress(
        "system-design",
        LearningTrackProgressUpdateRequest(step_no=payload.step_no, completed=payload.completed),
        user,
    )
    return SystemDesignStepProgress(
        step_no=result.step_no,
        title=result.title,
        completed=result.completed,
        updated_at=result.updated_at,
    )

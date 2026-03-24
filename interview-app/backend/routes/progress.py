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
)
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client
from services.questions_service import find_qnum_by_question_id, get_question_summary_by_qnum

router = APIRouter(prefix="/progress", tags=["progress"])


def _status_from_state(outcome: str, revisit: bool) -> str:
    if revisit:
        return "revisit"
    return "good" if outcome == "solved" else "skip"


def _coerce_state_from_payload(payload: ProgressUpdateRequest, current_outcome: str, current_revisit: bool) -> tuple[str, bool]:
    outcome = current_outcome
    revisit = current_revisit

    # Legacy single-status compatibility.
    if payload.status:
        normalized = str(payload.status).lower().strip()
        if normalized in {"good", "strong"}:
            outcome = "solved"
            revisit = False
        elif normalized == "skip":
            outcome = "unsolved"
            revisit = False
        elif normalized == "revisit":
            revisit = True

    if payload.outcome:
        outcome = str(payload.outcome).lower().strip()

    if payload.revisit is not None:
        revisit = bool(payload.revisit)

    if outcome not in {"solved", "unsolved"}:
        outcome = "unsolved"

    return outcome, revisit


@router.post("/update")
def update_progress(payload: ProgressUpdateRequest, user: dict = Depends(get_current_user)):
    """Update question progress using outcome/revisit (or legacy status).

    Uses upsert so re-marking the same question just updates the status.
    """
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

    if payload.status is None and payload.outcome is None and payload.revisit is None:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one of: status, outcome, revisit.",
        )

    try:
        try:
            existing_rows = (
                supabase.table("user_progress")
                .select("outcome,is_revisit,status")
                .eq("user_id", user["id"])
                .eq("qnum", qnum)
                .limit(1)
                .execute()
            ).data or []
        except Exception:
            # Legacy schema compatibility (status-only rows).
            existing_rows = (
                supabase.table("user_progress")
                .select("status")
                .eq("user_id", user["id"])
                .eq("qnum", qnum)
                .limit(1)
                .execute()
            ).data or []

        existing = existing_rows[0] if existing_rows else {}
        current_outcome = str(existing.get("outcome") or "").lower().strip()
        current_revisit = bool(existing.get("is_revisit", False))

        # Backfill from legacy status when new columns are empty.
        if current_outcome not in {"solved", "unsolved"}:
            legacy_status = str(existing.get("status") or "").lower().strip()
            if legacy_status in {"good", "strong"}:
                current_outcome = "solved"
                current_revisit = False
            elif legacy_status == "revisit":
                current_outcome = "unsolved"
                current_revisit = True
            else:
                current_outcome = "unsolved"
                current_revisit = False

        next_outcome, next_revisit = _coerce_state_from_payload(payload, current_outcome, current_revisit)
        next_status = _status_from_state(next_outcome, next_revisit)

        try:
            supabase.table("user_progress").upsert(
                {
                    "user_id": user["id"],
                    "qnum": qnum,
                    "status": next_status,
                    "outcome": next_outcome,
                    "is_revisit": next_revisit,
                    "updated_at": now,
                },
                on_conflict="user_id,qnum",
            ).execute()
        except Exception:
            # Legacy schema fallback (without outcome/is_revisit columns).
            supabase.table("user_progress").upsert(
                {
                    "user_id": user["id"],
                    "qnum": qnum,
                    "status": next_status,
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
        "status": next_status,
        "outcome": next_outcome,
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

    # Calculate stats
    stats = ProgressStats(
        total_attempted=len(entries),
        strong_count=0,
        good_count=sum(
            1
            for e in entries
            if str(e.get("outcome") or "").lower() == "solved" or str(e.get("status") or "").lower() in {"good", "strong"}
        ),
        revisit_count=sum(
            1
            for e in entries
            if bool(e.get("is_revisit", False)) or str(e.get("status") or "").lower() == "revisit"
        ),
        skip_count=sum(
            1
            for e in entries
            if (
                str(e.get("outcome") or "").lower() == "unsolved" and not bool(e.get("is_revisit", False))
            ) or str(e.get("status") or "").lower() == "skip"
        ),
    )

    # Recent entries (last 20)
    recent = [
        ProgressEntry(
            qnum=e.get("qnum", 0),
            question_id=get_question_summary_by_qnum(e.get("qnum", 0)).get("question_id", ""),
            question_title=get_question_summary_by_qnum(e.get("qnum", 0)).get("question_title", f"Question #{e.get('qnum', 0)}"),
            company=get_question_summary_by_qnum(e.get("qnum", 0)).get("company", ""),
            difficulty=get_question_summary_by_qnum(e.get("qnum", 0)).get("difficulty", ""),
            status=(
                "revisit"
                if bool(e.get("is_revisit", False)) or str(e.get("status", "")).lower() == "revisit"
                else (
                    "good"
                    if str(e.get("outcome", "")).lower() == "solved" or str(e.get("status", "")).lower() in {"good", "strong"}
                    else "skip"
                )
            ),
            updated_at=e.get("updated_at", ""),
        )
        for e in entries[:20]
    ]

    return UserProgressResponse(stats=stats, recent=recent)


@router.get("/status/{qnum}", response_model=ProgressStatusResponse)
def get_question_progress_status(qnum: int, user: dict = Depends(get_current_user)):
    """Return saved status for one question, or null when not set."""
    if qnum <= 0:
        raise HTTPException(status_code=422, detail="qnum must be greater than 0")

    supabase = get_supabase_client()
    try:
        try:
            rows = (
                supabase.table("user_progress")
                .select("status,outcome,is_revisit")
                .eq("user_id", user["id"])
                .eq("qnum", qnum)
                .limit(1)
                .execute()
            ).data or []
        except Exception:
            rows = (
                supabase.table("user_progress")
                .select("status")
                .eq("user_id", user["id"])
                .eq("qnum", qnum)
                .limit(1)
                .execute()
            ).data or []
        status = rows[0].get("status") if rows else None
        outcome = rows[0].get("outcome") if rows else None
        revisit = bool(rows[0].get("is_revisit", False)) if rows else False

        if rows and outcome is None:
            legacy = str(status or "").lower()
            if legacy in {"good", "strong"}:
                outcome = "solved"
                revisit = False
            elif legacy == "revisit":
                outcome = "unsolved"
                revisit = True
            else:
                outcome = "unsolved"
                revisit = False
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return ProgressStatusResponse(qnum=qnum, status=status, outcome=outcome, revisit=revisit)


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

    return {"success": True, "qnum": qnum, "status": None}

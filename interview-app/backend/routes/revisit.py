"""Revisit queue routes — manage saved questions for later practice."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from models.schemas import RevisitResponse, RevisitEntry
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client
from services.questions_service import get_question_summary_by_qnum

router = APIRouter(prefix="/revisit", tags=["revisit"])


@router.get("", response_model=RevisitResponse)
def get_revisit_queue(user: dict = Depends(get_current_user)):
    """Return all questions in the user's revisit queue."""
    supabase = get_supabase_client()

    try:
        result = (
            supabase.table("user_progress")
            .select("*")
            .eq("user_id", user["id"])
            .eq("is_revisit", True)
            .order("updated_at", desc=True)
            .execute()
        )
        entries = result.data or []
    except Exception:
        # Backward compatibility: pre-migration rows without is_revisit may only have status='revisit'.
        try:
            fallback = (
                supabase.table("user_progress")
                .select("*")
                .eq("user_id", user["id"])
                .eq("status", "revisit")
                .order("updated_at", desc=True)
                .execute()
            )
            entries = fallback.data or []
        except Exception:
            entries = []

    items = [
        RevisitEntry(
            qnum=e.get("qnum", 0),
            question_id=get_question_summary_by_qnum(e.get("qnum", 0)).get("question_id", ""),
            question_title=get_question_summary_by_qnum(e.get("qnum", 0)).get("question_title", f"Question #{e.get('qnum', 0)}"),
            company=get_question_summary_by_qnum(e.get("qnum", 0)).get("company", ""),
            difficulty=get_question_summary_by_qnum(e.get("qnum", 0)).get("difficulty", ""),
            added_at=e.get("updated_at", ""),
        )
        for e in entries
    ]

    return RevisitResponse(items=items)


@router.delete("/{qnum}")
def remove_from_revisit(qnum: int, user: dict = Depends(get_current_user)):
    """Remove a question from revisit while preserving solved/unsolved outcome."""
    supabase = get_supabase_client()

    try:
        current_rows = (
            supabase.table("user_progress")
            .select("outcome,status")
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .limit(1)
            .execute()
        ).data or []

        current = current_rows[0] if current_rows else {}
        outcome = str(current.get("outcome") or "").lower().strip()
        legacy_status = str(current.get("status") or "").lower().strip()
        if outcome not in {"solved", "unsolved"}:
            outcome = "solved" if legacy_status in {"good", "strong"} else "unsolved"

        status = "good" if outcome == "solved" else "skip"

        try:
            supabase.table("user_progress").update(
                {"is_revisit": False, "outcome": outcome, "status": status}
            ).eq("user_id", user["id"]).eq("qnum", qnum).execute()
        except Exception:
            # Legacy schema fallback.
            supabase.table("user_progress").update(
                {"status": "skip"}
            ).eq("user_id", user["id"]).eq("qnum", qnum).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True}

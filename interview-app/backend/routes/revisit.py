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
    """Remove a question from revisit while preserving solved state."""
    supabase = get_supabase_client()

    try:
        current_rows = (
            supabase.table("user_progress")
            .select("is_solved")
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .limit(1)
            .execute()
        ).data or []

        current = current_rows[0] if current_rows else {}
        is_solved = bool(current.get("is_solved", False))

        supabase.table("user_progress").update(
            {"is_revisit": False, "is_solved": is_solved}
        ).eq("user_id", user["id"]).eq("qnum", qnum).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True}

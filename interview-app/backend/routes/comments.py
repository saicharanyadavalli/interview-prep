"""Comments routes — user notes/comments on questions."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from models.schemas import CommentRequest, CommentEntry, CommentsResponse
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client
from services.questions_service import find_qnum_by_question_id

router = APIRouter(prefix="/comments", tags=["comments"])


@router.post("/add")
def add_comment(payload: CommentRequest, user: dict = Depends(get_current_user)):
    """Save a comment/note for a question."""
    supabase = get_supabase_client()
    qnum = payload.qnum
    if qnum is None and payload.question_id:
        qnum = find_qnum_by_question_id(payload.question_id)

    if qnum is None:
        raise HTTPException(
            status_code=422,
            detail="Provide either a valid qnum or a resolvable question_id.",
        )

    try:
        existing = (
            supabase.table("user_comments")
            .select("id")
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = existing.data or []

        if rows:
            supabase.table("user_comments").update(
                {"comment_text": payload.comment_text}
            ).eq("id", rows[0].get("id", "")).eq("user_id", user["id"]).execute()
        else:
            supabase.table("user_comments").insert(
                {
                    "user_id": user["id"],
                    "qnum": qnum,
                    "comment_text": payload.comment_text,
                }
            ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True}


@router.get("/{qnum}", response_model=CommentsResponse)
def get_comments(qnum: int, user: dict = Depends(get_current_user)):
    """Get all comments for a question by the current user."""
    supabase = get_supabase_client()

    try:
        result = (
            supabase.table("user_comments")
            .select("*")
            .eq("user_id", user["id"])
            .eq("qnum", qnum)
            .order("created_at", desc=True)
            .execute()
        )
        entries = result.data or []
    except Exception:
        entries = []

    items = [
        CommentEntry(
            id=e.get("id", ""),
            qnum=e.get("qnum", 0),
            comment_text=e.get("comment_text", ""),
            created_at=e.get("created_at", ""),
        )
        for e in entries
    ]

    return CommentsResponse(comments=items)


@router.delete("/{comment_id}")
def delete_comment(comment_id: str, user: dict = Depends(get_current_user)):
    """Delete a specific comment."""
    supabase = get_supabase_client()

    try:
        supabase.table("user_comments").delete().eq(
            "id", comment_id
        ).eq("user_id", user["id"]).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True}

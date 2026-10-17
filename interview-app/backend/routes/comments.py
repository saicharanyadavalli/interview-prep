"""Comments routes — user notes/comments on questions in RDS."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException

from models.schemas import CommentRequest, CommentEntry, CommentsResponse
from routes.auth import get_current_user
from services import rds_client
from services.questions_service import find_qnum_by_question_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/comments", tags=["comments"])


@router.post("/add")
def add_comment(payload: CommentRequest, user: dict = Depends(get_current_user)):
    """Save or update a comment/note for a question in RDS."""
    qnum = payload.qnum
    if qnum is None and payload.question_id:
        qnum = find_qnum_by_question_id(payload.question_id)

    if qnum is None:
        raise HTTPException(status_code=422, detail="Provide either a valid qnum or resolvable question_id.")

    try:
        existing = rds_client.query(
            "SELECT id FROM user_comments WHERE user_id = %s AND qnum = %s ORDER BY created_at DESC LIMIT 1;",
            (user["id"], qnum),
            fetch="one",
        )

        if existing:
            rds_client.mutate(
                "UPDATE user_comments SET comment_text = %s, created_at = now() WHERE id = %s AND user_id = %s;",
                (payload.comment_text, existing["id"], user["id"]),
            )
        else:
            rds_client.mutate(
                "INSERT INTO user_comments (user_id, qnum, comment_text, created_at) VALUES (%s, %s, %s, now());",
                (user["id"], qnum, payload.comment_text),
            )
    except Exception as exc:
        logger.error("add_comment RDS error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True}


@router.get("/{qnum}", response_model=CommentsResponse)
def get_comments(qnum: int, user: dict = Depends(get_current_user)):
    """Get all comments for a question by the current user from RDS."""
    try:
        entries = rds_client.query(
            "SELECT id, qnum, comment_text, created_at FROM user_comments WHERE user_id = %s AND qnum = %s ORDER BY created_at DESC;",
            (user["id"], qnum),
        ) or []
    except Exception as exc:
        logger.error("get_comments RDS error: %s", exc)
        entries = []

    items = [
        CommentEntry(
            id=str(e.get("id", "")),
            qnum=e.get("qnum", 0),
            comment_text=e.get("comment_text", ""),
            created_at=str(e.get("created_at", "")),
        )
        for e in entries
    ]

    return CommentsResponse(comments=items)


@router.delete("/{comment_id}")
def delete_comment(comment_id: str, user: dict = Depends(get_current_user)):
    """Delete a specific comment owned by the current user in RDS."""
    try:
        count = rds_client.mutate(
            "DELETE FROM user_comments WHERE id = %s AND user_id = %s;",
            (comment_id, user["id"]),
        )
        if count == 0:
            raise HTTPException(
                status_code=404,
                detail="Comment not found or access denied.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_comment RDS error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True}

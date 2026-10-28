"""Revisit queue routes — manage saved questions for later practice in RDS."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request

from limiter import limiter
from models.schemas import RevisitEntry, RevisitResponse
from routes.auth import get_current_user
from services import rds_client
from services.questions_service import get_question_summary_by_qnum

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/revisit", tags=["revisit"])


@router.get("", response_model=RevisitResponse)
@limiter.limit("60/minute")
def get_revisit_queue(request: Request, user: dict = Depends(get_current_user)):
    """Return all questions in the user's revisit queue from RDS."""
    try:
        entries = rds_client.query(
            """
            SELECT qnum, updated_at
            FROM user_progress
            WHERE user_id = %s AND is_revisit = true
            ORDER BY updated_at DESC;
            """,
            (user["id"],),
        ) or []
    except Exception as exc:
        logger.error("get_revisit_queue RDS error for user %s: %s", user.get("id"), exc)
        entries = []

    items = []
    for e in entries:
        qnum = int(e.get("qnum", 0) or 0)
        summary = get_question_summary_by_qnum(qnum)
        items.append(
            RevisitEntry(
                qnum=qnum,
                question_id=summary.get("question_id", ""),
                question_title=summary.get("question_title", f"Question #{qnum}"),
                company=summary.get("company", ""),
                difficulty=summary.get("difficulty", ""),
                added_at=str(e.get("updated_at", "")),
            )
        )

    return RevisitResponse(items=items)


@router.delete("/{qnum}")
@limiter.limit("30/minute")
def remove_from_revisit(request: Request, qnum: int, user: dict = Depends(get_current_user)):
    """Remove a question from revisit in RDS while preserving solved state."""
    try:
        rds_client.mutate(
            "UPDATE user_progress SET is_revisit = false, updated_at = now() WHERE user_id = %s AND qnum = %s;",
            (user["id"], qnum),
        )
    except Exception as exc:
        logger.error("remove_from_revisit RDS error for user %s, qnum %d: %s", user.get("id"), qnum, exc)
        raise HTTPException(status_code=500, detail="An error occurred while updating revisit list.") from exc

    return {"success": True}

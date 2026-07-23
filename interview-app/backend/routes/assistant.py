"""AI Assistant routes — ask doubts about interview questions."""

from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from routes.auth import get_current_user

from models.schemas import AskRequest, AskResponse
from services.gemini_service import ask_gemini_stream, is_in_scope
from limiter import limiter

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask")
@limiter.limit("20/hour")
def ask_assistant(request: Request, payload: AskRequest, current_user: dict = Depends(get_current_user)):
    """Send a doubt about an interview question to the AI assistant.

    The AI will respond with hints and guidance without revealing
    the full solution unless explicitly asked.
    """
    # Check if the doubt is related to DSA / the question
    history_dump = [m.model_dump() for m in payload.conversation_history]

    if not is_in_scope(payload.interview_question, payload.user_doubt, history_dump):
        def out_of_scope_gen():
            yield "data: " + json.dumps({"text": "I can only help with DSA interview topics related to the current question. Please ask about algorithm ideas, edge cases, complexity, or hints for this problem."}) + "\n\n"
        return StreamingResponse(out_of_scope_gen(), media_type="text/event-stream")

    def event_stream():
        try:
            for chunk in ask_gemini_stream(
                interview_question=payload.interview_question,
                user_doubt=payload.user_doubt,
                conversation_history=history_dump,
            ):
                yield "data: " + json.dumps({"text": chunk}) + "\n\n"
        except RuntimeError as exc:
            yield "data: " + json.dumps({"error": str(exc)}) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"error": f"Gemini API call failed: {exc}"}) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

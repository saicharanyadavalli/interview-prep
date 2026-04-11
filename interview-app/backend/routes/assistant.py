"""AI Assistant routes — ask doubts about interview questions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.schemas import AskRequest, AskResponse
from services.gemini_service import ask_gemini, is_in_scope

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=AskResponse)
def ask_assistant(payload: AskRequest):
    """Send a doubt about an interview question to the AI assistant.

    The AI will respond with hints and guidance without revealing
    the full solution unless explicitly asked.
    """
    # Check if the doubt is related to DSA / the question
    history_dump = [m.model_dump() for m in payload.conversation_history]

    if not is_in_scope(payload.interview_question, payload.user_doubt, history_dump):
        return AskResponse(
            answer=(
                "I can only help with DSA interview topics related to the current question. "
                "Please ask about algorithm ideas, edge cases, complexity, or hints for this problem."
            )
        )

    try:
        answer = ask_gemini(
            interview_question=payload.interview_question,
            user_doubt=payload.user_doubt,
            conversation_history=history_dump,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API call failed: {exc}",
        ) from exc

    return AskResponse(answer=answer)

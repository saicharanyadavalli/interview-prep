"""FastAPI backend for AI Interview Assistant using Google Gemini."""

from __future__ import annotations

import os
from typing import Optional

import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from prompt_builder import build_interview_assistant_prompt


class ChatMessage(BaseModel):
    """Single chat turn provided by frontend."""

    role: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    """Incoming request payload for /ask."""

    interview_question: str = Field(..., min_length=1)
    user_doubt: str = Field(..., min_length=1)
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class AskResponse(BaseModel):
    """Outgoing response payload for /ask."""

    answer: str


app = FastAPI(title="AI Interview Assistant Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


MODEL_NAME = "gemini-2.5-flash"

DSA_KEYWORDS = {
    "array",
    "string",
    "linked list",
    "stack",
    "queue",
    "tree",
    "graph",
    "heap",
    "hash",
    "dynamic programming",
    "dp",
    "greedy",
    "recursion",
    "backtracking",
    "binary search",
    "two pointer",
    "sliding window",
    "complexity",
    "time complexity",
    "space complexity",
    "bfs",
    "dfs",
    "sorting",
    "prefix sum",
    "bit",
    "trie",
    "union find",
    "disjoint set",
    "topological",
    "segment tree",
    "test case",
    "test cases",
    "dry run",
    "edge case",
    "corner case",
    "example",
    "intuition",
    "approach",
}

OUT_OF_SCOPE_KEYWORDS = {
    "weather",
    "temperature",
    "cricket score",
    "football",
    "movie",
    "song",
    "travel",
    "politics",
    "stock market",
    "bitcoin price",
    "joke",
    "recipe",
    "news",
}


def _get_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Missing GEMINI_API_KEY environment variable.",
        )
    return api_key


def _extract_text(response: object) -> str:
    """Extract plain text from Gemini response in a defensive way."""
    text_value: Optional[str] = getattr(response, "text", None)
    if text_value and text_value.strip():
        return text_value.strip()

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        chunks = []
        for part in parts:
            piece = getattr(part, "text", None)
            if piece:
                chunks.append(piece)
        if chunks:
            return "\n".join(chunks).strip()

    return "I could not generate a response. Please try again."


def _is_dsa_related(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in DSA_KEYWORDS)


def _is_clearly_out_of_scope(text: str) -> bool:
    lowered = text.strip().lower()
    return any(keyword in lowered for keyword in OUT_OF_SCOPE_KEYWORDS)


def _is_in_scope(interview_question: str, user_doubt: str) -> bool:
    if _is_clearly_out_of_scope(user_doubt):
        return False

    if _is_dsa_related(user_doubt):
        return True

    # Allow follow-up references that point back to the current question context.
    context_clues = (
        "this question",
        "this problem",
        "above",
        "approach",
        "solution",
        "hint",
        "test case",
        "test cases",
        "more examples",
        "dry run",
        "edge case",
        "explain",
    )
    if any(token in user_doubt.lower() for token in context_clues):
        return _is_dsa_related(interview_question)

    # If the base interview question is DSA, allow general follow-ups unless clearly unrelated.
    return _is_dsa_related(interview_question)


@app.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest) -> AskResponse:
    """Generate interview guidance using Gemini based on a question and a doubt."""
    if not _is_in_scope(payload.interview_question, payload.user_doubt):
        return AskResponse(
            answer=(
                "I can only help with DSA interview topics related to the current question. "
                "Please ask about algorithm ideas, edge cases, complexity, or hints for this problem."
            )
        )

    api_key = _get_api_key()
    genai.configure(api_key=api_key)

    prompt = build_interview_assistant_prompt(
        interview_question=payload.interview_question,
        user_doubt=payload.user_doubt,
        conversation_history=[m.model_dump() for m in payload.conversation_history],
    )

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API call failed: {exc}",
        ) from exc

    answer = _extract_text(response)
    return AskResponse(answer=answer)


# Example curl request:
# curl -X POST "http://127.0.0.1:8000/ask" \
#   -H "Content-Type: application/json" \
#   -d '{"interview_question":"Given an array, find two numbers that sum to target.","user_doubt":"How should I think about time complexity here?"}'

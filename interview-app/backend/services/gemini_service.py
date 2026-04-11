"""Gemini AI service — prompt building and API calls.

Ported from the existing backend/main.py and backend/prompt_builder.py
in the original prototype.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import google.generativeai as genai


MODEL_NAME = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Scope-checking keyword sets (from the original prototype)
# ---------------------------------------------------------------------------

DSA_KEYWORDS = {
    "array", "string", "linked list", "stack", "queue", "tree", "graph",
    "heap", "hash", "dynamic programming", "dp", "greedy", "recursion",
    "backtracking", "binary search", "two pointer", "sliding window",
    "complexity", "time complexity", "space complexity", "bfs", "dfs",
    "sorting", "prefix sum", "bit", "trie", "union find", "disjoint set",
    "topological", "segment tree", "test case", "test cases", "dry run",
    "edge case", "corner case", "example", "intuition", "approach",
}

OUT_OF_SCOPE_KEYWORDS = {
    "weather", "temperature", "cricket score", "football", "movie",
    "song", "travel", "politics", "stock market", "bitcoin price",
    "joke", "recipe", "news",
}

FOLLOW_UP_TOKENS = {
    "why", "how", "what", "where", "when", "can", "could", "should",
    "explain", "hint", "help", "stuck", "confused", "again", "detail",
    "elaborate", "understand", "clarify", "logic", "step", "steps",
    "approach", "solution", "complexity", "optimize", "dry run",
    "edge case", "test case", "failing", "fails", "wrong", "error",
}

QUESTION_CONTEXT_CLUES = {
    "this question", "this problem", "current question", "current problem",
    "above question", "above problem", "my code", "my approach", "my solution",
    "my logic", "where am i wrong", "what am i missing", "next step",
    "give a hint", "can you explain", "explain this", "dry run", "edge case",
    "test case", "time complexity", "space complexity", "runtime error",
    "wrong answer", "tle", "optimize",
}

PROGRAMMING_CUES = {
    "input", "output", "constraint", "constraints", "example", "examples",
    "return", "function", "class", "array", "string", "integer", "int",
    "linked list", "node", "matrix", "index", "indices", "loop", "pointer",
    "recursion", "stack", "queue", "tree", "graph", "hash", "sort",
    "binary", "search", "prefix", "suffix", "subarray", "substring",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")
    return api_key


def _is_dsa_related(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return any(kw in lowered for kw in DSA_KEYWORDS)


def _is_clearly_out_of_scope(text: str) -> bool:
    return any(kw in text.strip().lower() for kw in OUT_OF_SCOPE_KEYWORDS)


def _looks_like_programming_text(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(token in lowered for token in PROGRAMMING_CUES):
        return True

    # Typical coding notation and complexity forms.
    code_markers = ("{", "}", "=>", "==", "!=", "<=", ">=", "[]", "()")
    if any(marker in lowered for marker in code_markers):
        return True
    if re.search(r"\bo\s*\(", lowered):
        return True
    return False


def _looks_like_question_follow_up(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(token in lowered for token in QUESTION_CONTEXT_CLUES):
        return True

    words = re.findall(r"[a-zA-Z']+", lowered)
    if not words:
        return False

    # Short follow-up questions like "why?", "explain", "hint please".
    short_follow_up = len(words) <= 8 and any(token in lowered for token in FOLLOW_UP_TOKENS)
    return short_follow_up


def _has_recent_dsa_context(conversation_history: list[dict[str, str]] | None) -> bool:
    if not conversation_history:
        return False
    for item in conversation_history[-8:]:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if _is_dsa_related(content) or _looks_like_programming_text(content):
            return True
    return False


def is_in_scope(
    interview_question: str,
    user_doubt: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> bool:
    """Check whether a user doubt is related to DSA / the current question."""
    doubt = user_doubt.strip()
    question_text = interview_question.strip()

    if not doubt:
        return False

    doubt_is_dsa = _is_dsa_related(doubt) or _looks_like_programming_text(doubt)
    question_is_dsa = _is_dsa_related(question_text) or _looks_like_programming_text(question_text)

    if doubt_is_dsa:
        return True

    # Keep a firm block only for clearly unrelated prompts.
    if _is_clearly_out_of_scope(doubt) and not _looks_like_question_follow_up(doubt):
        return False

    if question_is_dsa and _looks_like_question_follow_up(doubt):
        return True

    # If the thread is already technical, allow terse follow-ups.
    if question_is_dsa and _has_recent_dsa_context(conversation_history):
        return True

    # Default: if current question context is technical, allow the doubt unless clearly out of scope.
    return question_is_dsa and not _is_clearly_out_of_scope(doubt)


# ---------------------------------------------------------------------------
# Prompt builder (from prompt_builder.py)
# ---------------------------------------------------------------------------

def _format_history(history: list[dict[str, str]] | None) -> str:
    if not history:
        return "(no prior conversation)"
    lines = []
    for item in history[-8:]:
        role = str(item.get("role", "user")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        speaker = "Assistant" if role == "assistant" else "User"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else "(no prior conversation)"


def build_prompt(
    interview_question: str,
    user_doubt: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Build the full Gemini prompt from user inputs."""
    history_text = _format_history(conversation_history)
    return f"""SYSTEM ROLE:
You are an AI Interview Assistant helping software engineering candidates understand interview problems without directly giving the full solution unless explicitly requested.

RULES:

* Do NOT immediately give the full solution.
* Provide hints instead of full answers when possible.
* Explain concepts clearly.
* If the user asks about complexity or algorithm intuition, explain step-by-step.
* Encourage the candidate to think.
* Only answer questions related to DSA and the given interview question context.
* If the user asks something outside DSA or unrelated to the interview question, politely refuse and redirect them back to the current problem.

INPUTS:
Interview Question:
{interview_question}

User Doubt:
{user_doubt}

Conversation History:
{history_text}

OUTPUT STYLE:

* Clear explanation
* Bullet points when helpful
* Hints instead of full answers
* Concise and interview-friendly
* Return plain text only.
* Do not use markdown symbols like **, *, `, or headings.
"""


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------

def _extract_text(response: object) -> str:
    """Extract plain text from Gemini response defensively."""
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


def ask_gemini(
    interview_question: str,
    user_doubt: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Send a prompt to Gemini and return the plain-text answer."""
    api_key = _get_api_key()
    genai.configure(api_key=api_key)

    prompt = build_prompt(interview_question, user_doubt, conversation_history)

    model = genai.GenerativeModel(MODEL_NAME)
    response = model.generate_content(prompt)
    return _extract_text(response)

"""Prompt construction utilities for the Interview Assistant backend."""

from __future__ import annotations


def _format_history(conversation_history: list[dict[str, str]] | None) -> str:
    if not conversation_history:
        return "(no prior conversation)"

    lines = []
    for item in conversation_history[-8:]:
        role = str(item.get("role", "user")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        speaker = "Assistant" if role == "assistant" else "User"
        lines.append(f"{speaker}: {content}")

    return "\n".join(lines) if lines else "(no prior conversation)"


def build_interview_assistant_prompt(
    interview_question: str,
    user_doubt: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Build a deterministic prompt for Gemini based on user inputs."""
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
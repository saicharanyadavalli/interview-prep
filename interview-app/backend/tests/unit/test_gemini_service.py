"""Unit tests for Gemini service heuristics, prompt construction, and response parsing."""

import pytest
from services.gemini_service import (
    is_in_scope,
    _is_dsa_related,
    _is_clearly_out_of_scope,
    _looks_like_programming_text,
    _looks_like_question_follow_up,
    build_prompt,
    _extract_text,
)


# ── Scope Classifier Tests ───────────────────────────────────────────────────

@pytest.mark.parametrize("dsa_doubt", [
    "How do I use two pointers to solve this in O(N)?",
    "What is the space complexity of recursion tree?",
    "Can I use dynamic programming or greedy approach?",
    "How does binary search handle edge cases?",
    "What is the time complexity of heap sort?",
])
def test_is_in_scope_accepts_dsa_queries(dsa_doubt: str):
    """Verify DSA questions and algorithm complexity questions are in-scope."""
    assert is_in_scope(interview_question="Two Sum", user_doubt=dsa_doubt) is True


@pytest.mark.parametrize("off_topic_doubt", [
    "What is the weather in Paris today?",
    "Tell me a recipe for chocolate cake",
    "Tell me a funny joke about cats",
    "What is the latest political news in Europe?",
])
def test_is_in_scope_rejects_off_topic_queries(off_topic_doubt: str):
    """Verify clearly out-of-scope non-technical queries are rejected."""
    assert is_in_scope(interview_question="Two Sum", user_doubt=off_topic_doubt) is False


def test_is_in_scope_accepts_terse_follow_up_with_dsa_question():
    """Verify short follow-up doubts ('why?', 'hint please', 'explain this') are allowed in DSA context."""
    assert is_in_scope(
        interview_question="Given an array of integers, find the maximum subarray sum.",
        user_doubt="why?",
    ) is True


def test_is_in_scope_empty_doubt_returns_false():
    """Verify empty doubt returns False."""
    assert is_in_scope(interview_question="Two Sum", user_doubt="   ") is False


# ── Prompt Construction Tests ────────────────────────────────────────────────

def test_build_prompt_contains_rules_and_inputs():
    """Verify build_prompt correctly formats system instructions and conversation history."""
    prompt = build_prompt(
        interview_question="Reverse a Linked List",
        user_doubt="Can I do it iteratively?",
        conversation_history=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ],
    )

    assert "SYSTEM ROLE:" in prompt
    assert "Reverse a Linked List" in prompt
    assert "Can I do it iteratively?" in prompt
    assert "User: Hello" in prompt
    assert "Assistant: Hi! How can I help?" in prompt


# ── Text Extraction Tests ────────────────────────────────────────────────────

def test_extract_text_from_object_with_text_attribute():
    """Verify _extract_text retrieves plain string from response.text."""
    class FakeResponse:
        text = "  Extracted response text  "

    assert _extract_text(FakeResponse()) == "Extracted response text"


def test_extract_text_from_candidate_parts_fallback():
    """Verify _extract_text handles candidates fallback structure."""
    class FakePart:
        text = "Chunk part 1"

    class FakeContent:
        parts = [FakePart()]

    class FakeCandidate:
        content = FakeContent()

    class FakeResponse:
        text = None
        candidates = [FakeCandidate()]

    assert _extract_text(FakeResponse()) == "Chunk part 1"

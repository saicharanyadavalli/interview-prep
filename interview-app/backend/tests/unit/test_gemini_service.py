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
    assert "<user_doubt>" in prompt and "</user_doubt>" in prompt
    assert "untrusted student input" in prompt


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



# ── Rate Limit Fallback Tests (Offline Mocked) ────────────────────────────────

def test_ask_gemini_falls_back_on_rate_limit(monkeypatch):
    """Verify ask_gemini automatically falls back to gemini-3.1-flash-lite on 429 / ResourceExhausted."""
    from unittest.mock import MagicMock
    from services.gemini_service import ask_gemini
    import google.generativeai as genai

    monkeypatch.setenv("GEMINI_API_KEY", "mock-test-key")
    monkeypatch.setenv("GEMINI_PRIMARY_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")

    models_called = []

    def mock_generative_model(model_name):
        models_called.append(model_name)
        mock_instance = MagicMock()
        if model_name == "gemini-3.5-flash-lite":
            # Simulate 429 / ResourceExhausted exception
            exc = Exception("429 ResourceExhausted: Quota exceeded for gemini-3.5-flash-lite")
            mock_instance.generate_content.side_effect = exc
        else:
            # Fallback model succeeds
            resp = MagicMock()
            resp.text = "Fallback model response successful"
            mock_instance.generate_content.return_value = resp
        return mock_instance

    monkeypatch.setattr(genai, "GenerativeModel", mock_generative_model)

    result = ask_gemini(
        interview_question="Two Sum",
        user_doubt="How to use hashmap?",
    )

    assert models_called == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    assert result == "Fallback model response successful"


def test_ask_gemini_stream_falls_back_on_rate_limit(monkeypatch):
    """Verify ask_gemini_stream automatically falls back to gemini-3.1-flash-lite on 429."""
    from unittest.mock import MagicMock
    from services.gemini_service import ask_gemini_stream
    import google.generativeai as genai

    monkeypatch.setenv("GEMINI_API_KEY", "mock-test-key")
    monkeypatch.setenv("GEMINI_PRIMARY_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")

    models_called = []

    def mock_generative_model(model_name):
        models_called.append(model_name)
        mock_instance = MagicMock()
        if model_name == "gemini-3.5-flash-lite":
            exc = Exception("429 ResourceExhausted: Quota exceeded")
            mock_instance.generate_content.side_effect = exc
        else:
            chunk1 = MagicMock()
            chunk1.text = "Streaming "
            chunk2 = MagicMock()
            chunk2.text = "from fallback"
            mock_instance.generate_content.return_value = [chunk1, chunk2]
        return mock_instance

    monkeypatch.setattr(genai, "GenerativeModel", mock_generative_model)

    chunks = list(ask_gemini_stream(
        interview_question="Two Sum",
        user_doubt="How to use hashmap?",
    ))

    assert models_called == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    assert "".join(chunks) == "Streaming from fallback"

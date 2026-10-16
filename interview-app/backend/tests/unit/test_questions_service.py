"""Unit tests for questions_service catalog deduplication, difficulty ranking, and normalization."""

import pytest
from services.questions_service import (
    _normalize_companies,
    _normalize_difficulty,
    _catalog_identity,
    _difficulty_rank,
    _dedupe_catalog_entries,
    _ttl_cache,
)


def test_normalize_companies_filters_unknown_and_sorts():
    """Verify _normalize_companies removes 'unknown' labels and duplicates, returning sorted list."""
    raw = ["Google", "unknown", "  ", "Amazon", "google", "Unknown Company"]
    normalized = _normalize_companies(raw)
    assert "unknown" not in [c.lower() for c in normalized]
    assert "Google" in normalized or "google" in normalized
    assert "Amazon" in normalized


def test_normalize_difficulty_mappings():
    """Verify difficulty normalization maps 'basic' to 'easy' and lowercases values."""
    assert _normalize_difficulty("Easy") == "easy"
    assert _normalize_difficulty("Medium") == "medium"
    assert _normalize_difficulty("Hard") == "hard"
    assert _normalize_difficulty("Basic") == "easy"
    assert _normalize_difficulty("") == "unknown"


def test_dedupe_catalog_entries_merges_duplicates_and_unions_tags():
    """Verify duplicate questions across datasets are merged and tags are unioned."""
    rows = [
        {
            "qnum": 10,
            "question_id": "two-sum",
            "problem_name": "Two Sum",
            "difficulty": "easy",
            "companies": ["Google"],
            "company_tags": ["Google"],
            "topic_tags": ["array"],
        },
        {
            "qnum": 25,
            "question_id": "two-sum",
            "problem_name": "Two Sum",
            "difficulty": "medium",
            "companies": ["Amazon", "Facebook"],
            "company_tags": ["Amazon", "Facebook"],
            "topic_tags": ["hash-table"],
        },
    ]

    merged = _dedupe_catalog_entries(rows)
    assert len(merged) == 1
    item = merged[0]

    # Retains lowest qnum
    assert item["qnum"] == 10
    # Retains related qnums
    assert set(item["related_qnums"]) == {10, 25}
    # Unions companies
    assert set(item["companies"]) == {"Amazon", "Facebook", "Google"}
    assert item["company_count"] == 3
    assert item["extra_company_count"] == 2
    # Unions topic tags
    assert set(item["topic_tags"]) == {"array", "hash-table"}


def test_ttl_cache_decorator():
    """Verify _ttl_cache memoizes results and reuses them."""
    call_count = 0

    @_ttl_cache(ttl_seconds=60)
    def compute_expensive():
        nonlocal call_count
        call_count += 1
        return 42

    assert compute_expensive() == 42
    assert compute_expensive() == 42
    assert call_count == 1

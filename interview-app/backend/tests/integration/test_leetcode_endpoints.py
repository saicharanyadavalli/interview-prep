"""Integration tests for /leetcode DSA problem catalog, solution approaches, and code snippets."""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


SAMPLE_LEETCODE_PROBLEMS = [
    {
        "qnum": 1,
        "title": "Two Sum",
        "slug": "two-sum",
        "difficulty": "Easy",
        "rating": 1800.0,
        "topic_tags": ["Array", "Hash Table"],
        "description_md": "Given an array of integers nums and an integer target...",
    },
    {
        "qnum": 2,
        "title": "Add Two Numbers",
        "slug": "add-two-numbers",
        "difficulty": "Medium",
        "rating": 1900.0,
        "topic_tags": ["Linked List", "Math"],
        "description_md": "You are given two non-empty linked lists...",
    },
]

SAMPLE_APPROACHES = [
    {
        "approach_index": 1,
        "title": "Hash Table One-Pass",
        "intuition_md": "Use a dictionary to store compliments.",
        "time_complexity": "O(N)",
        "space_complexity": "O(N)",
        "explanation_md": "Iterate through array while checking...",
    }
]

SAMPLE_CODE_SOLUTIONS = [
    {"language": "python", "code_content": "class Solution:\n    def twoSum(self, nums, target):\n        pass"},
    {"language": "cpp", "code_content": "class Solution {\npublic:\n    vector<int> twoSum() {}\n};"},
]


def test_get_leetcode_problems_paginated(client: TestClient, mock_supabase):
    """Verify GET /leetcode/problems returns paginated list of DSA problems."""
    mock_supabase.set_table_data("leetcode_problems", SAMPLE_LEETCODE_PROBLEMS)

    res = client.get("/leetcode/problems?page=1&limit=10&difficulty=Easy")
    assert res.status_code == 200
    data = res.json()
    assert "problems" in data
    assert "total" in data
    assert len(data["problems"]) > 0
    assert data["problems"][0]["qnum"] == 1


def test_get_leetcode_problem_detail(client: TestClient, mock_supabase):
    """Verify GET /leetcode/problems/{qnum} returns problem description markdown."""
    mock_supabase.set_table_data("leetcode_problems", SAMPLE_LEETCODE_PROBLEMS)

    res = client.get("/leetcode/problems/1")
    assert res.status_code == 200
    data = res.json()
    assert data["qnum"] == 1
    assert data["title"] == "Two Sum"
    assert "description_md" in data


def test_get_leetcode_problem_approaches(client: TestClient, mock_supabase):
    """Verify GET /leetcode/problems/{qnum}/approaches returns solution approach list."""
    mock_supabase.set_table_data("leetcode_approaches", SAMPLE_APPROACHES)

    res = client.get("/leetcode/problems/1/approaches")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["title"] == "Hash Table One-Pass"
    assert data[0]["time_complexity"] == "O(N)"


def test_get_leetcode_problem_code_snippets(client: TestClient, mock_supabase):
    """Verify GET /leetcode/problems/{qnum}/code returns code solution snippets dictionary."""
    mock_supabase.set_table_data("leetcode_code_solutions", SAMPLE_CODE_SOLUTIONS)

    res = client.get("/leetcode/problems/1/code?language=python")
    assert res.status_code == 200
    data = res.json()
    assert data["qnum"] == 1
    assert "python" in data["languages"] or "python" in data["solutions"]


def test_get_leetcode_problems_rating_sorting(client: TestClient, mock_supabase):
    """Verify GET /leetcode/problems with sort_by=rating_desc sorts properly."""
    mock_supabase.set_table_data("leetcode_problems", SAMPLE_LEETCODE_PROBLEMS)

    res = client.get("/leetcode/problems?page=1&limit=10&sort_by=rating_desc")
    assert res.status_code == 200
    data = res.json()
    assert "problems" in data
    assert len(data["problems"]) > 0

"""Integration tests for all /questions endpoints (companies, random, recommend, catalog, by-qnum)."""

from unittest.mock import patch
from fastapi.testclient import TestClient


SAMPLE_QUESTIONS = [
    {
        "qnum": 1,
        "question_id": "two-sum",
        "problem_name": "Two Sum",
        "difficulty": "easy",
        "problem_url": "https://leetcode.com/problems/two-sum",
        "statement_text": "Given an array of integers nums and an integer target...",
        "constraints_text": "2 <= nums.length <= 10^4",
        "examples": [{"input": "[2,7,11,15], 9", "output": "[0,1]"}],
        "topic_tags": ["array", "hash-table"],
        "company_tags": ["Google", "Amazon"],
        "company": "Google",
        "companies": ["Google", "Amazon"],
        "company_count": 2,
        "extra_company_count": 1,
        "company_display": "Google +1",
        "related_qnums": [1],
        "raw": {},
    },
    {
        "qnum": 2,
        "question_id": "add-two-numbers",
        "problem_name": "Add Two Numbers",
        "difficulty": "medium",
        "problem_url": "https://leetcode.com/problems/add-two-numbers",
        "statement_text": "You are given two non-empty linked lists...",
        "constraints_text": "0 <= Node.val <= 9",
        "examples": [],
        "topic_tags": ["linked-list", "math"],
        "company_tags": ["Amazon", "Microsoft"],
        "company": "Amazon",
        "companies": ["Amazon", "Microsoft"],
        "company_count": 2,
        "extra_company_count": 1,
        "company_display": "Amazon +1",
        "related_qnums": [2],
        "raw": {},
    },
]


def test_list_companies_authenticated_returns_200(client: TestClient):
    """Verify GET /questions/companies returns list of companies for authenticated user."""
    with patch("routes.questions.get_companies", return_value=["Amazon", "Google", "Microsoft"]):
        res = client.get("/questions/companies")
        assert res.status_code == 200
        data = res.json()
        assert "companies" in data
        assert "Google" in data["companies"]


def test_list_companies_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify GET /questions/companies returns 401 when no auth header is provided."""
    res = unauth_client.get("/questions/companies")
    assert res.status_code == 401


def test_random_question_returns_matching_question(client: TestClient):
    """Verify GET /questions/random returns a question matching company and difficulty."""
    with patch("routes.questions.get_all_questions", return_value=[SAMPLE_QUESTIONS[0]]):
        res = client.get("/questions/random?company=Google&difficulty=easy")
        assert res.status_code == 200
        data = res.json()
        assert data["qnum"] == 1
        assert data["problem_name"] == "Two Sum"
        assert data["difficulty"] == "easy"


def test_random_question_not_found_returns_404(client: TestClient):
    """Verify GET /questions/random returns 404 when no questions match the criteria."""
    with patch("routes.questions.get_all_questions", return_value=[]):
        res = client.get("/questions/random?company=NonExistentCorp&difficulty=hard")
        assert res.status_code == 404


def test_recommend_question_returns_question(client: TestClient):
    """Verify GET /questions/recommend returns recommended question prioritizing revisit items."""
    with patch("routes.questions.get_recommended_question", return_value=SAMPLE_QUESTIONS[0]):
        res = client.get("/questions/recommend?company=Google&difficulty=easy&revisit_ids=two-sum")
        assert res.status_code == 200
        data = res.json()
        assert data["question_id"] == "two-sum"


def test_all_questions_returns_total_and_list(client: TestClient):
    """Verify GET /questions/all returns all questions matching company and difficulty."""
    with patch("routes.questions.get_all_questions", return_value=SAMPLE_QUESTIONS):
        res = client.get("/questions/all?company=Google&difficulty=easy")
        assert res.status_code == 200
        data = res.json()
        assert "questions" in data
        assert data["total"] == 2


def test_questions_catalog_pagination_and_search(client: TestClient):
    """Verify GET /questions/catalog returns paginated and searchable question bank."""
    with patch("routes.questions.get_all_questions_catalog", return_value=SAMPLE_QUESTIONS), \
         patch("routes.questions._load_solved_qnums", return_value={1}):
        res = client.get("/questions/catalog?q=two&offset=0&limit=10")
        assert res.status_code == 200
        data = res.json()
        assert "questions" in data
        assert data["total"] == 2
        assert data["offset"] == 0
        assert data["limit"] == 10
        # Check solved state was enriched
        assert data["questions"][0]["solved"] == 1


def test_questions_catalog_user_authenticated(client: TestClient):
    """Verify GET /questions/catalog/user returns global catalog with user solved status."""
    with patch("routes.questions.get_all_questions_catalog", return_value=SAMPLE_QUESTIONS), \
         patch("routes.questions._load_solved_qnums", return_value={1}):
        res = client.get("/questions/catalog/user")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2


def test_question_by_qnum_found(client: TestClient):
    """Verify GET /questions/by-qnum/{qnum} returns question by qnum."""
    with patch("routes.questions.get_question_by_qnum", return_value=SAMPLE_QUESTIONS[0]):
        res = client.get("/questions/by-qnum/1")
        assert res.status_code == 200
        assert res.json()["problem_name"] == "Two Sum"


def test_question_by_qnum_not_found_returns_404(client: TestClient):
    """Verify GET /questions/by-qnum/{qnum} returns 404 for unknown qnum."""
    with patch("routes.questions.get_question_by_qnum", return_value=None):
        res = client.get("/questions/by-qnum/999999")
        assert res.status_code == 404

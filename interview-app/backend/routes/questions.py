"""Question routes — random, recommend, companies, and bulk list."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Depends, HTTPException

from models.schemas import QuestionResponse, CompaniesResponse
from routes.auth import get_current_user, get_optional_current_user
from services.supabase_client import get_supabase_client
from services.questions_service import (
    get_companies,
    get_random_question,
    get_recommended_question,
    get_all_questions,
    get_all_questions_catalog,
    get_question_by_qnum,
)

router = APIRouter(prefix="/questions", tags=["questions"])

_ALLOWED_STATUSES = {"strong", "good", "revisit", "skip", "solved", "unsolved"}
_ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
_ALLOWED_MATCH_TYPES = {"all", "any"}


def _parse_filter_tokens(raw: str | None) -> list[tuple[str, str]]:
    """Parse comma-separated filter values into [(operator, value)] tokens.

    Supports:
    - "strong,good" -> [("is", "strong"), ("is", "good")]
    - "!skip" -> [("is_not", "skip")]
    """
    if not raw:
        return []

    tokens: list[tuple[str, str]] = []
    for part in str(raw).split(","):
        item = part.strip().lower()
        if not item:
            continue
        if item.startswith("!"):
            value = item[1:].strip()
            if value:
                tokens.append(("is_not", value))
        else:
            tokens.append(("is", item))
    return tokens


def _as_tag_set(values: list[str] | None) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def _load_user_status_map(user_id: str, qnums: list[int]) -> dict[int, str]:
    if not user_id or not qnums:
        return {}

    supabase = get_supabase_client()
    try:
        try:
            rows = (
                supabase.table("user_progress")
                .select("qnum,status,outcome,is_revisit")
                .eq("user_id", user_id)
                .in_("qnum", qnums)
                .execute()
            ).data or []
        except Exception:
            rows = (
                supabase.table("user_progress")
                .select("qnum,status")
                .eq("user_id", user_id)
                .in_("qnum", qnums)
                .execute()
            ).data or []
    except Exception:
        return {}

    result: dict[int, str] = {}
    for row in rows:
        qnum = int(row.get("qnum", 0) or 0)
        status = str(row.get("status", "")).strip().lower()
        outcome = str(row.get("outcome", "")).strip().lower()
        is_revisit = bool(row.get("is_revisit", False))

        if qnum <= 0:
            continue

        if is_revisit or status == "revisit":
            result[qnum] = "revisit"
        elif outcome == "solved" or status in {"good", "strong"}:
            result[qnum] = "solved"
        elif outcome == "unsolved" or status == "skip":
            result[qnum] = "unsolved"
        elif status:
            result[qnum] = status
    return result


def _condition_match(field_value: str | set[str], operator: str, expected: str) -> bool:
    if isinstance(field_value, set):
        contains = expected in field_value
        return contains if operator == "is" else (not contains)

    eq = field_value == expected
    return eq if operator == "is" else (not eq)


def _filter_questions_rows(
    questions: list[dict],
    *,
    status_tokens: list[tuple[str, str]],
    difficulty_tokens: list[tuple[str, str]],
    topic_tokens: list[tuple[str, str]],
    company_tokens: list[tuple[str, str]],
    match_type: str,
    status_map: dict[int, str] | None = None,
) -> list[dict]:
    status_map = status_map or {}
    match_mode = match_type if match_type in _ALLOWED_MATCH_TYPES else "all"

    normalized_status_tokens = [(op, v) for op, v in status_tokens if v in _ALLOWED_STATUSES]
    normalized_difficulty_tokens = [(op, v) for op, v in difficulty_tokens if v in _ALLOWED_DIFFICULTIES]
    normalized_topic_tokens = [(op, v) for op, v in topic_tokens if v]
    normalized_company_tokens = [(op, v) for op, v in company_tokens if v]

    all_conditions = []
    all_conditions.extend(("status", op, val) for op, val in normalized_status_tokens)
    all_conditions.extend(("difficulty", op, val) for op, val in normalized_difficulty_tokens)
    all_conditions.extend(("topic", op, val) for op, val in normalized_topic_tokens)
    all_conditions.extend(("company", op, val) for op, val in normalized_company_tokens)

    if not all_conditions:
        return questions

    filtered: list[dict] = []
    for question in questions:
        qnum = int(question.get("qnum", 0) or 0)
        status_value = str(status_map.get(qnum, "")).strip().lower()
        difficulty_value = str(question.get("difficulty", "")).strip().lower()
        topic_set = _as_tag_set(question.get("topic_tags") or [])
        company_set = _as_tag_set(
            list(question.get("companies") or [])
            + list(question.get("company_tags") or [])
            + ([question.get("company", "")] if question.get("company") else [])
            + ([question.get("company_display", "")] if question.get("company_display") else [])
        )

        checks: list[bool] = []
        for field, operator, expected in all_conditions:
            if field == "status":
                checks.append(_condition_match(status_value, operator, expected))
            elif field == "difficulty":
                checks.append(_condition_match(difficulty_value, operator, expected))
            elif field == "topic":
                checks.append(_condition_match(topic_set, operator, expected))
            elif field == "company":
                checks.append(_condition_match(company_set, operator, expected))

        if not checks:
            filtered.append(question)
        elif match_mode == "any" and any(checks):
            filtered.append(question)
        elif match_mode == "all" and all(checks):
            filtered.append(question)

    return filtered


def _apply_catalog_search(questions: list[dict], query: str | None) -> list[dict]:
    """Apply lightweight full-text search across key catalog fields."""
    if not query:
        return questions

    q = query.strip().lower()
    if not q:
        return questions

    filtered: list[dict] = []
    for item in questions:
        name = str(item.get("problem_name", "")).lower()
        company = str(item.get("company", "")).lower()
        companies = " ".join(item.get("companies", []) or []).lower()
        difficulty = str(item.get("difficulty", "")).lower()
        topic_tags = " ".join(item.get("topic_tags", []) or []).lower()
        company_tags = " ".join(item.get("company_tags", []) or []).lower()
        haystack = f"{name} {company} {companies} {difficulty} {topic_tags} {company_tags}"
        if q in haystack:
            filtered.append(item)

    return filtered


def _apply_pagination(rows: list[dict], offset: int, limit: int) -> list[dict]:
    """Return paginated list slice."""
    return rows[offset: offset + limit]


@router.get("/companies", response_model=CompaniesResponse)
def list_companies(current_user: dict = Depends(get_current_user)):
    """Return all available company names."""
    return CompaniesResponse(companies=get_companies())


@router.get("/random", response_model=QuestionResponse)
def random_question(
    company: str = Query(..., min_length=1),
    difficulty: str = Query(..., pattern="^(easy|medium|hard)$"),
    status: Optional[str] = Query(None, description="Status filter, supports !value for is-not"),
    topic: Optional[str] = Query(None, description="Topic filter, supports !value for is-not"),
    match: str = Query("all", pattern="^(all|any)$"),
    exclude: Optional[str] = Query(None, description="Comma-separated question IDs to exclude"),
    current_user: dict = Depends(get_current_user),
):
    """Return a random question for the given company and difficulty."""
    exclude_ids = [e.strip() for e in exclude.split(",") if e.strip()] if exclude else None
    questions = get_all_questions(company, difficulty)
    if exclude_ids:
        exclude_set = set(exclude_ids)
        questions = [q for q in questions if str(q.get("question_id", "")) not in exclude_set]

    status_tokens = _parse_filter_tokens(status)
    topic_tokens = _parse_filter_tokens(topic)
    if status_tokens or topic_tokens:
        qnums = [int(q.get("qnum", 0) or 0) for q in questions if int(q.get("qnum", 0) or 0) > 0]
        status_map = _load_user_status_map(current_user["id"], qnums)
        questions = _filter_questions_rows(
            questions,
            status_tokens=status_tokens,
            difficulty_tokens=[],
            topic_tokens=topic_tokens,
            company_tokens=[],
            match_type=match,
            status_map=status_map,
        )

    question = None
    if questions:
        import random
        question = random.choice(questions)

    if not question:
        raise HTTPException(
            status_code=404,
            detail=f"No questions found for {company} at {difficulty} difficulty.",
        )
    return QuestionResponse(**question)


@router.get("/recommend", response_model=QuestionResponse)
def recommend_question(
    company: str = Query(..., min_length=1),
    difficulty: str = Query(..., pattern="^(easy|medium|hard)$"),
    status: Optional[str] = Query(None, description="Status filter, supports !value for is-not"),
    topic: Optional[str] = Query(None, description="Topic filter, supports !value for is-not"),
    match: str = Query("all", pattern="^(all|any)$"),
    revisit_ids: Optional[str] = Query(None, description="Comma-separated revisit queue IDs"),
    exclude: Optional[str] = Query(None, description="Comma-separated seen question IDs"),
    current_user: dict = Depends(get_current_user),
):
    """Return a recommended question, prioritizing revisit queue items."""
    r_ids = [e.strip() for e in revisit_ids.split(",") if e.strip()] if revisit_ids else None
    e_ids = [e.strip() for e in exclude.split(",") if e.strip()] if exclude else None
    question = get_recommended_question(company, difficulty, r_ids, e_ids)

    if question:
        filtered = _filter_questions_rows(
            [question],
            status_tokens=_parse_filter_tokens(status),
            difficulty_tokens=[],
            topic_tokens=_parse_filter_tokens(topic),
            company_tokens=[],
            match_type=match,
            status_map=_load_user_status_map(current_user["id"], [int(question.get("qnum", 0) or 0)]),
        )
        if not filtered:
            question = None

    if not question:
        raise HTTPException(
            status_code=404,
            detail=f"No questions found for {company} at {difficulty} difficulty.",
        )
    return QuestionResponse(**question)


@router.get("/all")
def all_questions(
    company: str = Query(..., min_length=1),
    difficulty: str = Query(..., pattern="^(easy|medium|hard)$"),
    status: Optional[str] = Query(None, description="Status filter, supports !value for is-not"),
    topic: Optional[str] = Query(None, description="Topic filter, supports !value for is-not"),
    match: str = Query("all", pattern="^(all|any)$"),
    current_user: dict = Depends(get_current_user),
):
    """Return all questions for a company and difficulty (for client-side use)."""
    questions = get_all_questions(company, difficulty)
    status_tokens = _parse_filter_tokens(status)
    topic_tokens = _parse_filter_tokens(topic)
    if status_tokens or topic_tokens:
        qnums = [int(q.get("qnum", 0) or 0) for q in questions if int(q.get("qnum", 0) or 0) > 0]
        status_map = _load_user_status_map(current_user["id"], qnums)
        questions = _filter_questions_rows(
            questions,
            status_tokens=status_tokens,
            difficulty_tokens=[],
            topic_tokens=topic_tokens,
            company_tokens=[],
            match_type=match,
            status_map=status_map,
        )

    return {"questions": questions, "total": len(questions)}


@router.get("/catalog")
def all_questions_catalog(
    q: Optional[str] = Query(None, description="Search by question/company/difficulty/tags"),
    status: Optional[str] = Query(None, description="Status filter, supports !value for is-not"),
    difficulty: Optional[str] = Query(None, description="Difficulty filter, supports !value for is-not"),
    company: Optional[str] = Query(None, description="Company filter, supports !value for is-not"),
    topic: Optional[str] = Query(None, description="Topic filter, supports !value for is-not"),
    match: str = Query("all", pattern="^(all|any)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    current_user: dict | None = Depends(get_optional_current_user),
):
    """Return all questions across all companies and difficulties."""
    questions = get_all_questions_catalog()
    filtered = _apply_catalog_search(questions, q)

    status_tokens = _parse_filter_tokens(status)
    if status_tokens and not current_user:
        raise HTTPException(status_code=401, detail="Authentication required for status filter.")

    status_map = {}
    if current_user and status_tokens:
        qnums = [int(row.get("qnum", 0) or 0) for row in filtered if int(row.get("qnum", 0) or 0) > 0]
        status_map = _load_user_status_map(current_user["id"], qnums)

    filtered = _filter_questions_rows(
        filtered,
        status_tokens=status_tokens,
        difficulty_tokens=_parse_filter_tokens(difficulty),
        topic_tokens=_parse_filter_tokens(topic),
        company_tokens=_parse_filter_tokens(company),
        match_type=match,
        status_map=status_map,
    )

    paginated = _apply_pagination(filtered, offset, limit)
    return {
        "questions": paginated,
        "total": len(filtered),
        "offset": offset,
        "limit": limit,
    }


@router.get("/catalog/user")
def all_questions_catalog_user(
    q: Optional[str] = Query(None, description="Search by question/company/difficulty/tags"),
    solved: str = Query("all", pattern="^(all|solved|unsolved)$"),
    status: Optional[str] = Query(None, description="Status filter, supports !value for is-not"),
    difficulty: Optional[str] = Query(None, description="Difficulty filter, supports !value for is-not"),
    company: Optional[str] = Query(None, description="Company filter, supports !value for is-not"),
    topic: Optional[str] = Query(None, description="Topic filter, supports !value for is-not"),
    match: str = Query("all", pattern="^(all|any)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    current_user: dict = Depends(get_current_user),
):
    """Return global catalog with DB-backed solved status for current user."""
    questions = get_all_questions_catalog()
    supabase = get_supabase_client()

    try:
        try:
            progress_rows = (
                supabase.table("user_progress")
                .select("qnum,status,outcome")
                .eq("user_id", current_user["id"])
                .execute()
            ).data or []
        except Exception:
            progress_rows = (
                supabase.table("user_progress")
                .select("qnum,status")
                .eq("user_id", current_user["id"])
                .execute()
            ).data or []
        solved_qnums = {
            int(r.get("qnum", 0))
            for r in progress_rows
            if int(r.get("qnum", 0) or 0) > 0
            and (
                str(r.get("outcome", "")).lower() == "solved"
                or str(r.get("status", "")).lower() in {"good", "strong"}
            )
        }
    except Exception:
        solved_qnums = set()

    enriched = []
    for question_row in questions:
        qnum = int(question_row.get("qnum", 0) or 0)
        related_qnums = [int(v) for v in (question_row.get("related_qnums") or []) if int(v or 0) > 0]
        candidate_qnums = related_qnums if related_qnums else ([qnum] if qnum > 0 else [])
        item = dict(question_row)
        is_solved = any(candidate in solved_qnums for candidate in candidate_qnums)
        item["solved"] = 1 if is_solved else 0
        item["solved_label"] = "Solved" if is_solved else "Not Solved"
        enriched.append(item)

    filtered = _apply_catalog_search(enriched, q)
    filtered = _filter_questions_rows(
        filtered,
        status_tokens=_parse_filter_tokens(status),
        difficulty_tokens=_parse_filter_tokens(difficulty),
        topic_tokens=_parse_filter_tokens(topic),
        company_tokens=_parse_filter_tokens(company),
        match_type=match,
        status_map=_load_user_status_map(
            current_user["id"],
            [int(row.get("qnum", 0) or 0) for row in progress_rows if int(row.get("qnum", 0) or 0) > 0],
        ),
    )

    if solved == "solved":
        filtered = [item for item in filtered if int(item.get("solved", 0) or 0) == 1]
    elif solved == "unsolved":
        filtered = [item for item in filtered if int(item.get("solved", 0) or 0) == 0]

    paginated = _apply_pagination(filtered, offset, limit)
    return {
        "questions": paginated,
        "total": len(filtered),
        "offset": offset,
        "limit": limit,
    }


@router.get("/by-qnum/{qnum}", response_model=QuestionResponse)
def question_by_qnum(qnum: int, current_user: dict = Depends(get_current_user)):
    """Return one question by qnum."""
    question = get_question_by_qnum(qnum)
    if not question:
        raise HTTPException(status_code=404, detail=f"Question with qnum={qnum} not found.")
    return QuestionResponse(**question)

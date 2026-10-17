"""LeetCode master problems, approaches, and code solutions routes.

Authoritative data source: Amazon RDS PostgreSQL 17.11 (database: interview_prep_db).
Queries:
  - leetcode_problems
  - leetcode_approaches
  - leetcode_code_solutions
"""

from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import rds_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leetcode", tags=["leetcode"])


class LeetCodeProblemItem(BaseModel):
    qnum: int
    title: str
    slug: str
    difficulty: str
    rating: Optional[float] = None
    topic_tags: List[str] = []


class LeetCodeProblemListResponse(BaseModel):
    total: int
    page: int
    limit: int
    problems: List[LeetCodeProblemItem]


class ApproachItem(BaseModel):
    approach_index: int
    title: str
    intuition_md: str
    time_complexity: str
    space_complexity: str
    explanation_md: str


@router.get("/problems", response_model=LeetCodeProblemListResponse)
def get_leetcode_problems(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    difficulty: Optional[str] = Query(None, description="Easy, Medium, or Hard"),
    search: Optional[str] = Query(None, description="Search term matching title or exact qnum"),
    tag: Optional[str] = Query(None, description="Topic tag filter (e.g. Array, Dynamic Programming)"),
    sort_by: Optional[str] = Query(
        None,
        description="Sort order: rating_desc, rating_asc, qnum_asc, qnum_desc, difficulty_asc, difficulty_desc, title_asc",
    ),
):
    """Retrieve paginated LeetCode problems list from RDS with search, filters, and rating sorting."""
    offset = (page - 1) * limit

    where_clauses = []
    params: list = []

    if difficulty and isinstance(difficulty, str):
        diff_clean = difficulty.strip().capitalize()
        where_clauses.append("LOWER(difficulty) = LOWER(%s)")
        params.append(diff_clean)

    if search and isinstance(search, str):
        s_clean = search.strip()
        if s_clean.isdigit():
            where_clauses.append("qnum = %s")
            params.append(int(s_clean))
        else:
            where_clauses.append("title ILIKE %s")
            params.append(f"%{s_clean}%")

    if tag and isinstance(tag, str):
        tag_clean = tag.strip().title()
        where_clauses.append("topic_tags @> ARRAY[%s]::text[]")
        params.append(tag_clean)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Sort order
    if sort_by == "rating_desc":
        order_clause = "ORDER BY rating DESC NULLS LAST, qnum ASC"
    elif sort_by == "rating_asc":
        order_clause = "ORDER BY rating ASC NULLS LAST, qnum ASC"
    elif sort_by == "qnum_desc":
        order_clause = "ORDER BY qnum DESC"
    elif sort_by == "difficulty_asc":
        order_clause = "ORDER BY difficulty ASC, qnum ASC"
    elif sort_by == "difficulty_desc":
        order_clause = "ORDER BY difficulty DESC, qnum ASC"
    elif sort_by == "title_asc":
        order_clause = "ORDER BY title ASC"
    else:
        order_clause = "ORDER BY qnum ASC"

    try:
        count_sql = f"SELECT count(*) FROM leetcode_problems {where_sql};"
        total = int(rds_client.query(count_sql, tuple(params), fetch="scalar") or 0)

        query_sql = f"""
        SELECT qnum, title, slug, difficulty, rating, topic_tags
        FROM leetcode_problems
        {where_sql}
        {order_clause}
        LIMIT %s OFFSET %s;
        """
        rows = rds_client.query(query_sql, tuple(params + [limit, offset])) or []

        problems = []
        for r in rows:
            tags = r.get("topic_tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.strip("{}").split(",") if t.strip()]

            problems.append(
                LeetCodeProblemItem(
                    qnum=r["qnum"],
                    title=r["title"],
                    slug=r["slug"],
                    difficulty=r["difficulty"],
                    rating=float(r["rating"]) if r.get("rating") is not None else None,
                    topic_tags=tags,
                )
            )

        return LeetCodeProblemListResponse(total=total, page=page, limit=limit, problems=problems)
    except Exception as exc:
        logger.error("get_leetcode_problems RDS error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database query error: {exc}") from exc


@router.get("/problems/{qnum}")
def get_leetcode_problem_detail(qnum: int):
    """Get single LeetCode problem description from RDS by question number."""
    try:
        row = rds_client.query(
            """
            SELECT qnum, title, slug, difficulty, rating, topic_tags, description_md
            FROM leetcode_problems
            WHERE qnum = %s
            LIMIT 1;
            """,
            (qnum,),
            fetch="one",
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"LeetCode problem #{qnum} not found")

        tags = row.get("topic_tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.strip("{}").split(",") if t.strip()]

        return {
            "qnum": row["qnum"],
            "title": row["title"],
            "slug": row["slug"],
            "difficulty": row["difficulty"],
            "rating": float(row["rating"]) if row.get("rating") is not None else None,
            "topic_tags": tags,
            "description_md": row.get("description_md", ""),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_leetcode_problem_detail RDS error for qnum %d: %s", qnum, exc)
        raise HTTPException(status_code=500, detail=f"Database query error: {exc}") from exc


@router.get("/problems/{qnum}/approaches", response_model=List[ApproachItem])
def get_leetcode_problem_approaches(qnum: int):
    """Get solution explanation approaches for the Solution Accordion dropdown from RDS."""
    try:
        rows = rds_client.query(
            """
            SELECT approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md
            FROM leetcode_approaches
            WHERE qnum = %s
            ORDER BY approach_index ASC;
            """,
            (qnum,),
        ) or []

        return [
            ApproachItem(
                approach_index=r.get("approach_index", 1),
                title=r.get("title", ""),
                intuition_md=r.get("intuition_md") or "",
                time_complexity=r.get("time_complexity") or "",
                space_complexity=r.get("space_complexity") or "",
                explanation_md=r.get("explanation_md") or "",
            )
            for r in rows
        ]
    except Exception as exc:
        logger.error("get_leetcode_problem_approaches RDS error for qnum %d: %s", qnum, exc)
        raise HTTPException(status_code=500, detail=f"Database query error: {exc}") from exc


@router.get("/problems/{qnum}/code")
def get_leetcode_problem_code(qnum: int, language: Optional[str] = Query(None)):
    """Get code solution snippets for the Code Language Dropdown from RDS."""
    try:
        if language and isinstance(language, str):
            rows = rds_client.query(
                """
                SELECT language, code_content
                FROM leetcode_code_solutions
                WHERE qnum = %s AND LOWER(language) = LOWER(%s)
                ORDER BY language ASC;
                """,
                (qnum, language.strip()),
            ) or []
        else:
            rows = rds_client.query(
                """
                SELECT language, code_content
                FROM leetcode_code_solutions
                WHERE qnum = %s
                ORDER BY language ASC;
                """,
                (qnum,),
            ) or []

        solutions = {r["language"]: r["code_content"] for r in rows}
        return {
            "qnum": qnum,
            "languages": list(solutions.keys()),
            "solutions": solutions,
        }
    except Exception as exc:
        logger.error("get_leetcode_problem_code RDS error for qnum %d: %s", qnum, exc)
        raise HTTPException(status_code=500, detail=f"Database query error: {exc}") from exc

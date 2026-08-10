"""LeetCode DSA problems and multi-language solutions API router."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/leetcode", tags=["leetcode"])

DB_PATH = Path(__file__).resolve().parent.parent / "leetcode_dsa.db"


def _get_db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="LeetCode DSA database not initialized.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


class CodeSolutionItem(BaseModel):
    language: str
    code_content: str


@router.get("/problems", response_model=LeetCodeProblemListResponse)
def get_leetcode_problems(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    difficulty: Optional[str] = Query(None, description="Easy, Medium, or Hard"),
    search: Optional[str] = Query(None, description="Search title or number"),
    tag: Optional[str] = Query(None, description="Filter by topic tag"),
):
    """Retrieve paginated LeetCode problems list with optional search and filters."""
    conn = _get_db()
    cur = conn.cursor()

    where_clauses = []
    params = []

    if difficulty and isinstance(difficulty, str):
        where_clauses.append("LOWER(difficulty) = LOWER(?)")
        params.append(difficulty.strip())

    if search and isinstance(search, str):
        s_term = f"%{search.strip()}%"
        where_clauses.append("(title LIKE ? OR CAST(qnum AS TEXT) LIKE ?)")
        params.extend([s_term, s_term])

    if tag and isinstance(tag, str):
        t_term = f"%{tag.strip()}%"
        where_clauses.append("topic_tags LIKE ?")
        params.append(t_term)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Total count query
    cur.execute(f"SELECT COUNT(*) as count FROM leetcode_problems{where_sql}", params)
    total = cur.fetchone()["count"]

    # Paginated data query
    offset = (page - 1) * limit
    cur.execute(
        f"""
        SELECT qnum, title, slug, difficulty, rating, topic_tags 
        FROM leetcode_problems{where_sql}
        ORDER BY qnum ASC 
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    rows = cur.fetchall()

    problems = []
    for r in rows:
        try:
            tags = json.loads(r["topic_tags"]) if r["topic_tags"] else []
        except Exception:
            tags = []
        problems.append(
            LeetCodeProblemItem(
                qnum=r["qnum"],
                title=r["title"],
                slug=r["slug"],
                difficulty=r["difficulty"],
                rating=r["rating"],
                topic_tags=tags,
            )
        )

    conn.close()
    return LeetCodeProblemListResponse(total=total, page=page, limit=limit, problems=problems)


@router.get("/problems/{qnum}")
def get_leetcode_problem_detail(qnum: int):
    """Get single LeetCode problem description only by question number."""
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM leetcode_problems WHERE qnum = ?", (qnum,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"LeetCode problem #{qnum} not found")

    try:
        tags = json.loads(row["topic_tags"]) if row["topic_tags"] else []
    except Exception:
        tags = []

    res = {
        "qnum": row["qnum"],
        "title": row["title"],
        "slug": row["slug"],
        "difficulty": row["difficulty"],
        "rating": row["rating"],
        "topic_tags": tags,
        "description_md": row["description_md"],
    }
    conn.close()
    return res


@router.get("/problems/{qnum}/approaches", response_model=List[ApproachItem])
def get_leetcode_problem_approaches(qnum: int):
    """Get solution explanation approaches for the Solution Accordion dropdown."""
    conn = _get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md
        FROM leetcode_approaches
        WHERE qnum = ?
        ORDER BY approach_index ASC
        """,
        (qnum,),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        ApproachItem(
            approach_index=r["approach_index"],
            title=r["title"],
            intuition_md=r["intuition_md"] or "",
            time_complexity=r["time_complexity"] or "",
            space_complexity=r["space_complexity"] or "",
            explanation_md=r["explanation_md"] or "",
        )
        for r in rows
    ]


@router.get("/problems/{qnum}/code")
def get_leetcode_problem_code(qnum: int, language: Optional[str] = Query(None)):
    """Get code solution snippets for the Code Language Dropdown."""
    conn = _get_db()
    cur = conn.cursor()

    if language and isinstance(language, str):
        cur.execute(
            "SELECT language, code_content FROM leetcode_code_solutions WHERE qnum = ? AND LOWER(language) = LOWER(?)",
            (qnum, language.strip()),
        )
    else:
        cur.execute(
            "SELECT language, code_content FROM leetcode_code_solutions WHERE qnum = ? ORDER BY language ASC",
            (qnum,),
        )

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"qnum": qnum, "languages": [], "solutions": {}}

    solutions = {r["language"]: r["code_content"] for r in rows}
    return {
        "qnum": qnum,
        "languages": list(solutions.keys()),
        "solutions": solutions,
    }

"""LeetCode DSA problems and multi-language solutions API router."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from services.supabase_client import get_supabase_client

router = APIRouter(prefix="/leetcode", tags=["leetcode"])

DB_PATH = Path(__file__).resolve().parent.parent / "leetcode_dsa.db"


def _get_sqlite_db():
    if not DB_PATH.exists():
        return None
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
    limit: int = Query(25, ge=1, le=100),
    difficulty: Optional[str] = Query(None, description="Easy, Medium, or Hard"),
    search: Optional[str] = Query(None, description="Search title or number"),
    tag: Optional[str] = Query(None, description="Filter by topic tag"),
):
    """Retrieve paginated LeetCode problems list with optional search and filters."""
    offset = (page - 1) * limit

    # Primary: query Supabase cloud database
    try:
        supabase = get_supabase_client()
        query = supabase.table("leetcode_problems").select(
            "qnum, title, slug, difficulty, rating, topic_tags", count="exact"
        )

        if difficulty and isinstance(difficulty, str):
            diff_clean = difficulty.strip().capitalize()
            query = query.ilike("difficulty", diff_clean)

        if search and isinstance(search, str):
            s_clean = search.strip()
            if s_clean.isdigit():
                query = query.eq("qnum", int(s_clean))
            else:
                query = query.ilike("title", f"%{s_clean}%")

        query = query.order("qnum", desc=False).range(offset, offset + limit - 1)
        res = query.execute()

        total = res.count if res.count is not None else len(res.data or [])
        problems = []
        for r in res.data or []:
            tags = r.get("topic_tags")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []
            elif not isinstance(tags, list):
                tags = []

            problems.append(
                LeetCodeProblemItem(
                    qnum=r["qnum"],
                    title=r["title"],
                    slug=r["slug"],
                    difficulty=r["difficulty"],
                    rating=r.get("rating"),
                    topic_tags=tags,
                )
            )

        return LeetCodeProblemListResponse(
            total=total, page=page, limit=limit, problems=problems
        )
    except Exception as exc:
        pass

    # Fallback to local SQLite if available
    conn = _get_sqlite_db()
    if conn is None:
        return LeetCodeProblemListResponse(total=0, page=page, limit=limit, problems=[])

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

    cur.execute(f"SELECT COUNT(*) as count FROM leetcode_problems{where_sql}", params)
    total = cur.fetchone()["count"]

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
    # Primary: Supabase
    try:
        supabase = get_supabase_client()
        res = (
            supabase.table("leetcode_problems")
            .select("*")
            .eq("qnum", qnum)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            row = res.data[0]
            tags = row.get("topic_tags")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []
            elif not isinstance(tags, list):
                tags = []

            return {
                "qnum": row["qnum"],
                "title": row["title"],
                "slug": row["slug"],
                "difficulty": row["difficulty"],
                "rating": row.get("rating"),
                "topic_tags": tags,
                "description_md": row.get("description_md", ""),
            }
    except Exception:
        pass

    # Fallback: SQLite
    conn = _get_sqlite_db()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM leetcode_problems WHERE qnum = ?", (qnum,))
        row = cur.fetchone()
        conn.close()
        if row:
            try:
                tags = json.loads(row["topic_tags"]) if row["topic_tags"] else []
            except Exception:
                tags = []
            return {
                "qnum": row["qnum"],
                "title": row["title"],
                "slug": row["slug"],
                "difficulty": row["difficulty"],
                "rating": row["rating"],
                "topic_tags": tags,
                "description_md": row["description_md"],
            }

    raise HTTPException(status_code=404, detail=f"LeetCode problem #{qnum} not found")


@router.get("/problems/{qnum}/approaches", response_model=List[ApproachItem])
def get_leetcode_problem_approaches(qnum: int):
    """Get solution explanation approaches for the Solution Accordion dropdown."""
    # Primary: Supabase
    try:
        supabase = get_supabase_client()
        res = (
            supabase.table("leetcode_approaches")
            .select("*")
            .eq("qnum", qnum)
            .order("approach_index", desc=False)
            .execute()
        )
        if res.data is not None:
            return [
                ApproachItem(
                    approach_index=r.get("approach_index", 1),
                    title=r.get("title", ""),
                    intuition_md=r.get("intuition_md") or "",
                    time_complexity=r.get("time_complexity") or "",
                    space_complexity=r.get("space_complexity") or "",
                    explanation_md=r.get("explanation_md") or "",
                )
                for r in res.data
            ]
    except Exception:
        pass

    # Fallback: SQLite
    conn = _get_sqlite_db()
    if conn:
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

    return []


@router.get("/problems/{qnum}/code")
def get_leetcode_problem_code(qnum: int, language: Optional[str] = Query(None)):
    """Get code solution snippets for the Code Language Dropdown."""
    # Primary: Supabase
    try:
        supabase = get_supabase_client()
        query = supabase.table("leetcode_code_solutions").select("language, code_content").eq("qnum", qnum)
        if language and isinstance(language, str):
            query = query.ilike("language", language.strip())
        else:
            query = query.order("language", desc=False)
        res = query.execute()
        if res.data is not None:
            solutions = {r["language"]: r["code_content"] for r in res.data}
            return {
                "qnum": qnum,
                "languages": list(solutions.keys()),
                "solutions": solutions,
            }
    except Exception:
        pass

    # Fallback: SQLite
    conn = _get_sqlite_db()
    if conn:
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
        if rows:
            solutions = {r["language"]: r["code_content"] for r in rows}
            return {
                "qnum": qnum,
                "languages": list(solutions.keys()),
                "solutions": solutions,
            }

    return {"qnum": qnum, "languages": [], "solutions": {}}

"""Questions service — loads interview questions from the JSON data files.

The data lives in ../../output/stage3_company_wise/ relative to this file.
Each company has files like questions_detailed_easy.json, etc.
Questions are cached in memory after first load for performance.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from services.supabase_client import get_supabase_client

# Path to the output data directory (relative to this file's location)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output" / "stage3_company_wise"

# In-memory cache: key = "Company::difficulty" -> list of questions
_cache: dict[str, list[dict]] = {}

# Companies list cache
_companies: list[str] | None = None

# Lazy index: question_id -> qnum
_qid_to_qnum: dict[str, int] | None = None

# Lazy index: qnum -> formatted question summary
_qnum_to_summary: dict[int, dict] | None = None

# Cached flattened catalog across all companies/difficulties
_catalog_cache: list[dict] | None = None

_DB_QUESTIONS_TABLE = "question_bank_questions"
_DB_ALIASES_TABLE = "question_bank_qnum_aliases"
_DB_PAGE_SIZE = 1000


def _normalize_companies(values: list[str] | None) -> list[str]:
    """Return clean company labels, dropping empty/unknown placeholders."""
    cleaned = {
        str(value).strip()
        for value in (values or [])
        if str(value).strip() and str(value).strip().lower() != "unknown"
    }
    return sorted(cleaned)


def _is_unknown_company(value: str) -> bool:
    return str(value or "").strip().lower() in {"", "unknown", "unknown company"}


def _companies_json_path() -> Path:
    """Path to the companies.json file in the web/ directory."""
    return Path(__file__).resolve().parent.parent.parent.parent / "web" / "companies.json"


def _normalize_difficulty(value: str) -> str:
    """Normalize difficulty text to lowercase variants used across the app."""
    normalized = str(value or "").strip().lower()
    if normalized in {"easy", "medium", "hard"}:
        return normalized
    if normalized == "basic":
        return "easy"
    return normalized or "unknown"


def _format_db_question(row: dict) -> dict:
    """Format one DB row into the standard question response shape."""
    companies = _normalize_companies(row.get("companies") or [])
    company_tags = _normalize_companies(row.get("company_tags") or [])
    if not companies and company_tags:
        companies = company_tags

    raw_primary_company = str(row.get("primary_company") or "").strip()
    if _is_unknown_company(raw_primary_company):
        raw_primary_company = ""

    primary_company = raw_primary_company or (companies[0] if companies else "General")
    company_count = int(row.get("company_count", len(companies)) or len(companies))
    extra_company_count = max(0, company_count - 1)

    source_qnums = [int(v) for v in (row.get("source_qnums") or []) if int(v or 0) > 0]
    all_qnums = sorted(set(source_qnums + [int(row.get("qnum", 0) or 0)]) - {0})

    formatted = {
        "qnum": int(row.get("qnum", 0) or 0),
        "question_id": row.get("question_id", ""),
        "problem_name": row.get("problem_name", "Untitled"),
        "difficulty": row.get("difficulty", "Unknown"),
        "problem_url": row.get("problem_url", ""),
        "statement_text": row.get("statement_text", ""),
        "constraints_text": row.get("constraints_text", ""),
        "examples": row.get("examples") or [],
        "topic_tags": row.get("topic_tags") or [],
        "company_tags": row.get("company_tags") or [],
        "raw": row.get("raw") or {},
        "company": primary_company,
        "companies": companies,
        "company_count": company_count,
        "extra_company_count": extra_company_count,
        "company_display": (
            f"{primary_company} +{extra_company_count}" if extra_company_count > 0 else primary_company
        ),
        "related_qnums": all_qnums,
    }
    return formatted


def _db_resolve_canonical_qnum(qnum: int) -> int | None:
    """Resolve source qnum to canonical qnum via alias table."""
    if qnum <= 0:
        return None

    try:
        supabase = get_supabase_client()
        row = (
            supabase.table(_DB_ALIASES_TABLE)
            .select("canonical_qnum")
            .eq("source_qnum", qnum)
            .limit(1)
            .execute()
        ).data or []
        if row:
            canonical = int(row[0].get("canonical_qnum", 0) or 0)
            if canonical > 0:
                return canonical
    except Exception:
        return None

    return None


def _catalog_identity(question: dict) -> str:
    """Return a canonical identity key used to merge duplicates across qnums."""
    question_id = str(question.get("question_id", "")).strip().lower()
    if question_id:
        return f"id::{question_id}"

    problem_url = str(question.get("problem_url", "")).strip().lower()
    if problem_url:
        return f"url::{problem_url}"

    problem_name = str(question.get("problem_name", "")).strip().lower()
    return f"name::{problem_name}"


def _difficulty_rank(value: str) -> int:
    normalized = _normalize_difficulty(value)
    if normalized == "easy":
        return 0
    if normalized == "medium":
        return 1
    if normalized == "hard":
        return 2
    return 3


def _dedupe_catalog_entries(rows: list[dict]) -> list[dict]:
    """Merge duplicate questions and aggregate company labels (e.g., Company +N)."""
    grouped: dict[str, dict] = {}

    for row in rows:
        key = _catalog_identity(row)
        qnum = int(row.get("qnum", 0) or 0)
        companies = set(_normalize_companies(row.get("companies", []) or []))
        company_tags = set(_normalize_companies(row.get("company_tags", []) or []))
        topic_tags = {
            str(value).strip().lower()
            for value in (row.get("topic_tags", []) or [])
            if str(value).strip()
        }
        fallback_company = str(row.get("company", "")).strip()
        if fallback_company and not _is_unknown_company(fallback_company):
            companies.add(fallback_company)

        existing = grouped.get(key)
        if existing is None:
            merged = dict(row)
            merged["companies"] = set(companies)
            merged["company_tags"] = set(company_tags)
            merged["topic_tags"] = set(topic_tags)
            merged["related_qnums"] = set([qnum] if qnum > 0 else [])
            grouped[key] = merged
            continue

        existing["companies"].update(companies)
        existing["company_tags"].update(company_tags)
        existing["topic_tags"].update(topic_tags)
        if qnum > 0:
            existing["related_qnums"].add(qnum)

        existing_qnum = int(existing.get("qnum", 0) or 0)
        if existing_qnum <= 0 or (qnum > 0 and qnum < existing_qnum):
            existing["qnum"] = qnum

        existing_diff = str(existing.get("difficulty", ""))
        incoming_diff = str(row.get("difficulty", ""))
        if _difficulty_rank(incoming_diff) < _difficulty_rank(existing_diff):
            existing["difficulty"] = row.get("difficulty", existing_diff)

    deduped: list[dict] = []
    for merged in grouped.values():
        companies_sorted = _normalize_companies(list(merged.get("companies", set())))
        fallback_company = str(merged.get("company", "")).strip()
        if _is_unknown_company(fallback_company):
            fallback_company = ""
        primary_company = companies_sorted[0] if companies_sorted else (fallback_company or "General")
        related_qnums_sorted = sorted({int(q) for q in merged.get("related_qnums", set()) if int(q) > 0})
        company_count = len(companies_sorted)
        extra_company_count = max(0, company_count - 1)

        merged["companies"] = companies_sorted
        merged["company_tags"] = sorted({str(v) for v in merged.get("company_tags", set()) if str(v).strip()})
        merged["topic_tags"] = sorted({str(v) for v in merged.get("topic_tags", set()) if str(v).strip()})
        merged["company"] = primary_company
        merged["company_count"] = company_count
        merged["extra_company_count"] = extra_company_count
        merged["company_display"] = (
            f"{primary_company} +{extra_company_count}" if extra_company_count > 0 else primary_company
        )
        merged["related_qnums"] = related_qnums_sorted
        deduped.append(merged)

    deduped.sort(key=lambda item: int(item.get("qnum", 0) or 0))
    return deduped


def _db_fetch_catalog_rows() -> list[dict] | None:
    """Fetch all catalog rows from Supabase, or None when DB table is unavailable."""
    try:
        supabase = get_supabase_client()
    except Exception:
        return None

    rows: list[dict] = []
    offset = 0

    try:
        while True:
            batch = (
                supabase.table(_DB_QUESTIONS_TABLE)
                .select(
                    "qnum,question_id,problem_name,difficulty,problem_url,"
                    "statement_text,constraints_text,examples,topic_tags,"
                    "company_tags,raw,primary_company,companies,company_count,source_qnums"
                )
                .order("qnum")
                .range(offset, offset + _DB_PAGE_SIZE - 1)
                .execute()
            ).data or []

            if not batch:
                break

            rows.extend(batch)

            if len(batch) < _DB_PAGE_SIZE:
                break

            offset += _DB_PAGE_SIZE
    except Exception:
        return None

    return rows


def _db_fetch_question_rows_by_qnums(qnums: list[int]) -> dict[int, dict] | None:
    """Fetch question rows for qnums from Supabase as a qnum->row map."""
    if not qnums:
        return {}

    try:
        supabase = get_supabase_client()
        data = (
            supabase.table(_DB_QUESTIONS_TABLE)
            .select(
                "qnum,question_id,problem_name,difficulty,problem_url,"
                "statement_text,constraints_text,examples,topic_tags,"
                "company_tags,raw,primary_company,companies,company_count,source_qnums"
            )
            .in_("qnum", qnums)
            .execute()
        ).data or []
    except Exception:
        return None

    return {int(row.get("qnum", 0) or 0): row for row in data}


def _db_fetch_questions_for_company_difficulty(company: str, difficulty: str) -> list[dict] | None:
    """Fetch question rows for (company, difficulty) using company_tags in question table."""
    normalized_company = str(company or "").strip().lower()
    if not normalized_company:
        return []

    try:
        supabase = get_supabase_client()
    except Exception:
        return None

    rows: list[dict] = []
    offset = 0
    normalized_difficulty = _normalize_difficulty(difficulty)

    try:
        while True:
            batch = (
                supabase.table(_DB_QUESTIONS_TABLE)
                .select(
                    "qnum,question_id,problem_name,difficulty,problem_url,"
                    "statement_text,constraints_text,examples,topic_tags,"
                    "company_tags,raw,primary_company,companies,company_count,source_qnums"
                )
                .eq("difficulty", normalized_difficulty)
                .order("qnum")
                .range(offset, offset + _DB_PAGE_SIZE - 1)
                .execute()
            ).data or []

            if not batch:
                break

            for row in batch:
                tags = {
                    str(value).strip().lower()
                    for value in (row.get("company_tags") or [])
                    if str(value).strip()
                }
                if normalized_company in tags:
                    rows.append(row)

            if len(batch) < _DB_PAGE_SIZE:
                break

            offset += _DB_PAGE_SIZE
    except Exception:
        return None

    return rows


def get_companies() -> list[str]:
    """Return the list of available companies."""
    global _companies
    if _companies is not None:
        return _companies

    # DB-first: pull distinct companies from company_tags in question rows.
    try:
        supabase = get_supabase_client()
        rows: list[dict] = []
        offset = 0
        while True:
            batch = (
                supabase.table(_DB_QUESTIONS_TABLE)
                .select("company_tags")
                .order("qnum")
                .range(offset, offset + _DB_PAGE_SIZE - 1)
                .execute()
            ).data or []

            if not batch:
                break

            rows.extend(batch)

            if len(batch) < _DB_PAGE_SIZE:
                break

            offset += _DB_PAGE_SIZE

        companies = sorted(
            {
                str(company).strip()
                for row in rows
                for company in (row.get("company_tags") or [])
                if str(company).strip() and not _is_unknown_company(str(company).strip())
            }
        )
        if companies:
            _companies = companies
            return _companies
    except Exception:
        pass

    path = _companies_json_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            _companies = json.load(f)
    else:
        # Fallback: scan directory names
        if _BASE_DIR.exists():
            _companies = sorted([
                d.name for d in _BASE_DIR.iterdir() if d.is_dir()
            ])
        else:
            _companies = []
    return _companies


def _load_questions(company: str, difficulty: str) -> list[dict]:
    """Load questions from the JSON file for a given company and difficulty."""
    cache_key = f"{company}::{difficulty}"
    if cache_key in _cache:
        return _cache[cache_key]

    file_path = _BASE_DIR / company / f"questions_detailed_{difficulty}.json"
    if not file_path.exists():
        _cache[cache_key] = []
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        data = []

    _cache[cache_key] = data
    return data


def _normalize_question(item: dict) -> dict:
    """Normalize a question dict, handling the problem_page wrapper."""
    core = item.get("problem_page", item) if isinstance(item, dict) else item
    if not isinstance(core, dict):
        core = {}
    return core


def _question_id(item: dict) -> str:
    """Generate a unique ID for a question."""
    core = _normalize_question(item)
    return core.get("slug") or core.get("problem_url") or core.get("problem_name") or "unknown"


def _format_question(item: dict) -> dict:
    """Format a raw question dict into a clean API response shape."""
    core = _normalize_question(item)
    return {
        "qnum": int(item.get("qnum", 0) or 0),
        "question_id": _question_id(item),
        "problem_name": core.get("problem_name", "Untitled"),
        "difficulty": core.get("difficulty", "Unknown"),
        "problem_url": core.get("problem_url", ""),
        "statement_text": core.get("statement_text", core.get("full_text", "")),
        "constraints_text": core.get("constraints_text", ""),
        "examples": core.get("examples", []),
        "topic_tags": core.get("topic_tags", []),
        "company_tags": core.get("company_tags", []),
        "raw": item,
    }


def get_random_question(
    company: str,
    difficulty: str,
    exclude_ids: list[str] | None = None,
) -> dict | None:
    """Return a random question, optionally excluding already-seen IDs."""
    questions = get_all_questions(company, difficulty)
    if not questions:
        return None

    if exclude_ids:
        exclude_set = set(exclude_ids)
        candidates = [q for q in questions if str(q.get("question_id", "")) not in exclude_set]
    else:
        candidates = questions

    if not candidates:
        # All exhausted, pick from full set
        candidates = questions

    return random.choice(candidates)


def get_recommended_question(
    company: str,
    difficulty: str,
    revisit_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
) -> dict | None:
    """Return a recommended question, prioritizing revisit queue items."""
    questions = get_all_questions(company, difficulty)
    if not questions:
        return None

    exclude_set = set(exclude_ids or [])

    # First try to find a revisit-queue question that hasn't been seen
    if revisit_ids:
        revisit_set = set(revisit_ids)
        revisit_candidates = [
            q for q in questions
            if str(q.get("question_id", "")) in revisit_set and str(q.get("question_id", "")) not in exclude_set
        ]
        if revisit_candidates:
            return random.choice(revisit_candidates)

    # Otherwise return any unseen question
    candidates = [q for q in questions if str(q.get("question_id", "")) not in exclude_set]
    if not candidates:
        candidates = questions

    return random.choice(candidates)


def get_all_questions(company: str, difficulty: str) -> list[dict]:
    """Return all questions for a company/difficulty pair, formatted."""
    db_rows = _db_fetch_questions_for_company_difficulty(company, difficulty)
    if db_rows is not None:
        return [_format_db_question(row) for row in db_rows]

    questions = _load_questions(company, difficulty)
    return [_format_question(q) for q in questions]


def get_all_questions_catalog() -> list[dict]:
    """Return a flattened catalog of all questions across all companies/difficulties."""
    global _catalog_cache

    if _catalog_cache is not None:
        return _catalog_cache

    db_rows = _db_fetch_catalog_rows()
    if db_rows is not None and db_rows:
        formatted_rows = [_format_db_question(row) for row in db_rows]
        _catalog_cache = _dedupe_catalog_entries(formatted_rows)
        return _catalog_cache

    catalog: dict[int, dict] = {}
    for company in get_companies():
        for difficulty in ("easy", "medium", "hard"):
            for item in _load_questions(company, difficulty):
                formatted = _format_question(item)
                qnum = int(formatted.get("qnum", 0) or 0)
                if qnum <= 0:
                    continue
                if qnum in catalog:
                    existing = catalog[qnum]
                    companies = existing.get("companies", [])
                    if company not in companies:
                        companies.append(company)
                    continue
                formatted["company"] = company
                formatted["difficulty"] = formatted.get("difficulty", difficulty)
                formatted["companies"] = [company]
                catalog[qnum] = formatted

    rows: list[dict] = []
    for qnum in sorted(catalog.keys()):
        row = catalog[qnum]
        companies = _normalize_companies(row.get("companies", []))
        fallback_company = str(row.get("company", "")).strip()
        if _is_unknown_company(fallback_company):
            fallback_company = ""
        primary_company = companies[0] if companies else (fallback_company or "General")
        company_count = len(companies)
        extra_company_count = max(0, company_count - 1)

        row["company"] = primary_company
        row["companies"] = companies
        row["company_count"] = company_count
        row["extra_company_count"] = extra_company_count
        row["company_display"] = (
            f"{primary_company} +{extra_company_count}" if extra_company_count > 0 else primary_company
        )
        rows.append(row)

    _catalog_cache = _dedupe_catalog_entries(rows)
    return _catalog_cache


def get_question_by_qnum(qnum: int) -> dict | None:
    """Return a single formatted question by qnum across all datasets."""
    if qnum <= 0:
        return None

    rows_map = _db_fetch_question_rows_by_qnums([qnum])
    if rows_map is not None and qnum in rows_map:
        return _format_db_question(rows_map[qnum])

    canonical_qnum = _db_resolve_canonical_qnum(qnum)
    if canonical_qnum and canonical_qnum != qnum:
        alias_rows_map = _db_fetch_question_rows_by_qnums([canonical_qnum])
        if alias_rows_map is not None and canonical_qnum in alias_rows_map:
            return _format_db_question(alias_rows_map[canonical_qnum])

    for company in get_companies():
        for difficulty in ("easy", "medium", "hard"):
            for item in _load_questions(company, difficulty):
                item_qnum = int(item.get("qnum", 0) or 0)
                if item_qnum == qnum:
                    formatted = _format_question(item)
                    formatted["company"] = company
                    formatted["difficulty"] = formatted.get("difficulty", difficulty)
                    return formatted
    return None


def find_qnum_by_question_id(question_id: str) -> int | None:
    """Resolve a numeric qnum from a question_id slug/URL/name identifier."""
    global _qid_to_qnum

    if not question_id:
        return None

    # Fast DB lookup when table exists.
    try:
        supabase = get_supabase_client()
        row = (
            supabase.table(_DB_QUESTIONS_TABLE)
            .select("qnum")
            .eq("question_id", question_id)
            .limit(1)
            .execute()
        ).data or []
        if row:
            qnum = int(row[0].get("qnum", 0) or 0)
            if qnum > 0:
                return qnum
    except Exception:
        pass

    if _qid_to_qnum is None:
        index: dict[str, int] = {}
        for company in get_companies():
            for difficulty in ("easy", "medium", "hard"):
                for item in _load_questions(company, difficulty):
                    qid = _question_id(item)
                    qnum = int(item.get("qnum", 0) or 0)
                    if qid and qnum > 0:
                        index[qid] = qnum
        _qid_to_qnum = index

    return _qid_to_qnum.get(question_id)


def get_question_summary_by_qnum(qnum: int) -> dict:
    """Return lightweight question metadata for a qnum if available."""
    global _qnum_to_summary

    if qnum <= 0:
        return {}

    rows_map = _db_fetch_question_rows_by_qnums([qnum])
    if rows_map is not None and qnum in rows_map:
        formatted = _format_db_question(rows_map[qnum])
        return {
            "qnum": qnum,
            "question_id": formatted.get("question_id", ""),
            "question_title": formatted.get("problem_name", ""),
            "company": formatted.get("company", ""),
            "difficulty": formatted.get("difficulty", ""),
        }

    canonical_qnum = _db_resolve_canonical_qnum(qnum)
    if canonical_qnum and canonical_qnum != qnum:
        alias_rows_map = _db_fetch_question_rows_by_qnums([canonical_qnum])
        if alias_rows_map is not None and canonical_qnum in alias_rows_map:
            formatted = _format_db_question(alias_rows_map[canonical_qnum])
            return {
                "qnum": canonical_qnum,
                "question_id": formatted.get("question_id", ""),
                "question_title": formatted.get("problem_name", ""),
                "company": formatted.get("company", ""),
                "difficulty": formatted.get("difficulty", ""),
            }

    if _qnum_to_summary is None:
        index: dict[int, dict] = {}
        for company in get_companies():
            for difficulty in ("easy", "medium", "hard"):
                for item in _load_questions(company, difficulty):
                    formatted = _format_question(item)
                    fqnum = int(formatted.get("qnum", 0) or 0)
                    if fqnum > 0 and fqnum not in index:
                        index[fqnum] = {
                            "qnum": fqnum,
                            "question_id": formatted.get("question_id", ""),
                            "question_title": formatted.get("problem_name", ""),
                            "company": company,
                            "difficulty": formatted.get("difficulty", difficulty),
                        }
        _qnum_to_summary = index

    return _qnum_to_summary.get(qnum, {})

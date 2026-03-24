"""Load question bank JSON files into Supabase question_bank tables.

Usage:
    cd interview-app/backend
    python load_questions_to_supabase.py --truncate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent
WORKSPACE_DIR = APP_DIR.parent
OUTPUT_DIR = WORKSPACE_DIR / "output" / "stage3_company_wise"

QUESTIONS_TABLE = "question_bank_questions"
COMPANIES_TABLE = "question_bank_companies"
ALIASES_TABLE = "question_bank_qnum_aliases"
BATCH_SIZE = 500


def _load_env() -> tuple[str, str]:
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    load_dotenv(APP_DIR / ".env")
    load_dotenv(BACKEND_DIR / ".env", override=False)

    import os

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")
    return url, key


def _normalize_question(item: dict[str, Any]) -> dict[str, Any]:
    core = item.get("problem_page", item) if isinstance(item, dict) else {}
    return core if isinstance(core, dict) else {}


def _normalize_difficulty(value: str) -> str:
    diff = str(value or "").strip().lower()
    if diff == "basic":
        return "easy"
    if diff not in {"easy", "medium", "hard"}:
        return "easy"
    return diff


def _question_id(core: dict[str, Any]) -> str:
    return str(
        core.get("slug")
        or core.get("problem_url")
        or core.get("problem_name")
        or "unknown"
    )


def _canonical_identity(core: dict[str, Any]) -> str:
    """Build a stable identity key for deduping same questions across qnums."""
    slug = str(core.get("slug", "")).strip().lower()
    if slug:
        return f"slug::{slug}"

    problem_url = str(core.get("problem_url", "")).strip().lower()
    if problem_url:
        return f"url::{problem_url}"

    problem_name = " ".join(str(core.get("problem_name", "")).strip().lower().split())
    return f"name::{problem_name}"


def _difficulty_rank(value: str) -> int:
    diff = _normalize_difficulty(value)
    if diff == "easy":
        return 0
    if diff == "medium":
        return 1
    if diff == "hard":
        return 2
    return 3


def _chunks(items: list[dict[str, Any]], size: int):
    for idx in range(0, len(items), size):
        yield items[idx: idx + size]


def _build_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not OUTPUT_DIR.exists():
        raise FileNotFoundError(f"Question directory not found: {OUTPUT_DIR}")

    groups: dict[str, dict[str, Any]] = {}

    for company_dir in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not company_dir.is_dir():
            continue

        company = company_dir.name
        for difficulty in ("easy", "medium", "hard"):
            file_path = company_dir / f"questions_detailed_{difficulty}.json"
            if not file_path.exists():
                continue

            data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue

            for item in data:
                if not isinstance(item, dict):
                    continue

                qnum = int(item.get("qnum", 0) or 0)
                if qnum <= 0:
                    continue

                core = _normalize_question(item)
                question_id = _question_id(core)
                normalized_diff = _normalize_difficulty(core.get("difficulty", difficulty))

                identity = _canonical_identity(core)
                group = groups.get(identity)
                if group is None:
                    groups[identity] = {
                        "question_id": question_id,
                        "problem_name": str(core.get("problem_name", "Untitled")),
                        "difficulty": normalized_diff,
                        "problem_url": str(core.get("problem_url", "")),
                        "statement_text": str(core.get("statement_text", core.get("full_text", ""))),
                        "constraints_text": str(core.get("constraints_text", "")),
                        "examples": core.get("examples", []) if isinstance(core.get("examples", []), list) else [],
                        "topic_tags": set(core.get("topic_tags", []) if isinstance(core.get("topic_tags", []), list) else []),
                        "company_tags": set(core.get("company_tags", []) if isinstance(core.get("company_tags", []), list) else []),
                        "raw": item,
                        "source_qnums": set([qnum]),
                        "companies": set([company]),
                        "associations": set([(company, normalized_diff)]),
                    }
                    continue

                group["source_qnums"].add(qnum)
                group["companies"].add(company)
                group["associations"].add((company, normalized_diff))
                group["topic_tags"].update(core.get("topic_tags", []) if isinstance(core.get("topic_tags", []), list) else [])
                group["company_tags"].update(core.get("company_tags", []) if isinstance(core.get("company_tags", []), list) else [])

                current_diff = str(group.get("difficulty", "easy"))
                if _difficulty_rank(normalized_diff) < _difficulty_rank(current_diff):
                    group["difficulty"] = normalized_diff

                # Keep representative row tied to smallest observed qnum for stability.
                smallest_seen = min(group["source_qnums"])
                if qnum == smallest_seen:
                    group["raw"] = item
                    if question_id and question_id != "unknown":
                        group["question_id"] = question_id

    question_rows: list[dict[str, Any]] = []
    company_rows: list[dict[str, Any]] = []
    alias_rows: list[dict[str, Any]] = []

    sorted_groups = sorted(groups.values(), key=lambda g: min(g["source_qnums"]))
    for group in sorted_groups:
        source_qnums = sorted(group["source_qnums"])
        canonical_qnum = source_qnums[0]
        companies = sorted(group["companies"])
        primary_company = companies[0] if companies else "Unknown"

        for src_qnum in source_qnums:
            alias_rows.append({
                "source_qnum": src_qnum,
                "canonical_qnum": canonical_qnum,
            })

        for company, diff in sorted(group["associations"]):
            company_rows.append(
                {
                    "qnum": canonical_qnum,
                    "company": company,
                    "difficulty": diff,
                }
            )

        question_rows.append(
            {
                "qnum": canonical_qnum,
                "question_id": group["question_id"],
                "problem_name": group["problem_name"],
                "difficulty": group["difficulty"],
                "problem_url": group["problem_url"],
                "statement_text": group["statement_text"],
                "constraints_text": group["constraints_text"],
                "examples": group["examples"],
                "topic_tags": sorted({str(v) for v in group["topic_tags"] if str(v).strip()}),
                "company_tags": sorted({str(v) for v in group["company_tags"] if str(v).strip()}),
                "raw": group["raw"],
                "primary_company": primary_company,
                "companies": companies,
                "company_count": len(companies),
                "source_qnums": source_qnums,
            }
        )

    return question_rows, company_rows, alias_rows


def _upsert_batches(client: Any, table: str, rows: list[dict[str, Any]], conflict: str) -> None:
    for batch in _chunks(rows, BATCH_SIZE):
        client.table(table).upsert(batch, on_conflict=conflict).execute()


def main() -> None:
    from supabase import create_client  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description="Load question bank into Supabase")
    parser.add_argument("--truncate", action="store_true", help="Delete existing question bank rows before insert")
    args = parser.parse_args()

    url, key = _load_env()
    client = create_client(url, key)

    question_rows, company_rows, alias_rows = _build_rows()

    if args.truncate:
        client.table(ALIASES_TABLE).delete().neq("source_qnum", 0).execute()
        client.table(COMPANIES_TABLE).delete().neq("qnum", 0).execute()
        client.table(QUESTIONS_TABLE).delete().neq("qnum", 0).execute()

    _upsert_batches(client, QUESTIONS_TABLE, question_rows, "qnum")
    _upsert_batches(client, COMPANIES_TABLE, company_rows, "qnum,company,difficulty")
    _upsert_batches(client, ALIASES_TABLE, alias_rows, "source_qnum")

    print(f"Loaded {len(question_rows)} questions into {QUESTIONS_TABLE}")
    print(f"Loaded {len(company_rows)} company links into {COMPANIES_TABLE}")
    print(f"Loaded {len(alias_rows)} qnum aliases into {ALIASES_TABLE}")
    print(f"Merged duplicates: {max(0, len(alias_rows) - len(question_rows))}")


if __name__ == "__main__":
    main()

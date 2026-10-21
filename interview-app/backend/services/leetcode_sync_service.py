"""LeetCode problem database synchronization service.

Handles idempotent, transactional upserts of LeetCode problems, approaches,
and code solutions into Amazon RDS PostgreSQL 17.11 (database: interview_prep_db).
Maintains sync history and commit tracking for webhook deployments.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

from services import rds_client
from services.leetcode_parser import ParsedProblem, validate_problem

logger = logging.getLogger(__name__)


def _dict_row(cursor: Any, row: Any) -> Optional[dict[str, Any]]:
    """Convert cursor row to dictionary regardless of cursor factory."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(cursor, "description") and cursor.description:
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    try:
        return dict(row)
    except Exception:
        return None


class LeetCodeSyncService:
    """Service for synchronizing parsed LeetCode data into RDS PostgreSQL."""

    def __init__(self, rds_client_module: Optional[Any] = None) -> None:
        self.rds = rds_client_module or rds_client

    @contextmanager
    def _get_connection(self) -> Generator[Any, None, None]:
        """Context manager to acquire an active DB connection from pool or mock."""
        if hasattr(self.rds, "get_connection"):
            cm = self.rds.get_connection()
            with cm as conn:
                yield conn
        elif hasattr(self.rds, "get_db_pool"):
            with self.rds.get_db_pool().get_connection() as conn:
                yield conn
        else:
            raise RuntimeError("Unsupported RDS client interface: missing connection provider")

    def _execute_query(
        self, sql: str, params: Optional[tuple | list] = None, fetch: str = "all"
    ) -> Any:
        """Helper to run read queries via rds_client or direct connection."""
        if hasattr(self.rds, "execute_query"):
            return self.rds.execute_query(sql, params, fetch=fetch)
        elif hasattr(self.rds, "query"):
            return self.rds.query(sql, params, fetch=fetch)
        elif hasattr(self.rds, "get_db_pool"):
            return self.rds.get_db_pool().execute_query(sql, params, fetch=fetch)
        else:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    if fetch == "all":
                        rows = cur.fetchall()
                        return [_dict_row(cur, r) for r in rows]
                    elif fetch == "one":
                        r = cur.fetchone()
                        return _dict_row(cur, r)
                    elif fetch == "scalar":
                        r = cur.fetchone()
                        d = _dict_row(cur, r)
                        return next(iter(d.values())) if d else None
                    return None

    def _execute_mutation(
        self, sql: str, params: Optional[tuple | list] = None
    ) -> Any:
        """Helper to run write queries via rds_client or direct connection."""
        if hasattr(self.rds, "execute_mutation"):
            return self.rds.execute_mutation(sql, params)
        elif hasattr(self.rds, "mutate"):
            return self.rds.mutate(sql, params)
        elif hasattr(self.rds, "get_db_pool"):
            return self.rds.get_db_pool().execute_mutation(sql, params)
        else:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rowcount = cur.rowcount
                conn.commit()
                return rowcount

    def _resolve_slug(self, cursor: Any, parsed: ParsedProblem) -> str:
        """Resolve slug collisions with different questions to enforce uniqueness."""
        target_slug = parsed.slug
        cursor.execute(
            "SELECT qnum FROM public.leetcode_problems WHERE slug = %s AND qnum != %s;",
            (target_slug, parsed.qnum),
        )
        collision = cursor.fetchone()
        if collision:
            target_slug = f"{parsed.slug}-{parsed.qnum}"
            cursor.execute(
                "SELECT qnum FROM public.leetcode_problems WHERE slug = %s AND qnum != %s;",
                (target_slug, parsed.qnum),
            )
            if cursor.fetchone():
                target_slug = f"{parsed.slug}-q{parsed.qnum}"
        return target_slug

    def _compare_existing(
        self,
        cursor: Any,
        parsed: ParsedProblem,
        target_slug: str,
        existing_prob: dict[str, Any],
    ) -> list[str]:
        """Detect differences between existing database records and parsed problem data."""
        diff_fields: list[str] = []

        if existing_prob.get("title") != parsed.title:
            diff_fields.append("title")
        if existing_prob.get("slug") != target_slug:
            diff_fields.append("slug")
        if existing_prob.get("difficulty") != parsed.difficulty:
            diff_fields.append("difficulty")

        existing_tags = sorted(list(existing_prob.get("topic_tags") or []))
        parsed_tags = sorted(list(parsed.topic_tags or []))
        if existing_tags != parsed_tags:
            diff_fields.append("topic_tags")

        existing_desc = (existing_prob.get("description_md") or "").strip()
        parsed_desc = (parsed.description_md or "").strip()
        if existing_desc != parsed_desc:
            diff_fields.append("description_md")

        # Query and compare approaches
        cursor.execute(
            """
            SELECT approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md
            FROM public.leetcode_approaches
            WHERE qnum = %s
            ORDER BY approach_index ASC;
            """,
            (parsed.qnum,),
        )
        existing_approaches = [_dict_row(cursor, r) for r in cursor.fetchall()]
        if len(existing_approaches) != len(parsed.approaches):
            diff_fields.append(
                f"approaches_count ({len(existing_approaches)} vs {len(parsed.approaches)})"
            )
        else:
            for ea, pa in zip(existing_approaches, parsed.approaches):
                if (
                    ea.get("title") != pa.title
                    or (ea.get("intuition_md") or "").strip() != (pa.intuition_md or "").strip()
                    or (ea.get("time_complexity") or "").strip() != (pa.time_complexity or "").strip()
                    or (ea.get("space_complexity") or "").strip() != (pa.space_complexity or "").strip()
                    or (ea.get("explanation_md") or "").strip() != (pa.explanation_md or "").strip()
                ):
                    diff_fields.append(f"approach_{pa.approach_index}_content")
                    break

        # Query and compare code solutions
        cursor.execute(
            """
            SELECT language, code_content
            FROM public.leetcode_code_solutions
            WHERE qnum = %s;
            """,
            (parsed.qnum,),
        )
        existing_solutions = [_dict_row(cursor, r) for r in cursor.fetchall()]
        existing_sol_map = {
            r["language"]: (r.get("code_content") or "").strip()
            for r in existing_solutions
            if r and "language" in r
        }
        parsed_sol_map = {k: v.strip() for k, v in parsed.code_solutions.items()}

        if set(existing_sol_map.keys()) != set(parsed_sol_map.keys()):
            diff_fields.append("code_solutions_languages")
        else:
            for lang, code in parsed_sol_map.items():
                if existing_sol_map.get(lang) != code:
                    diff_fields.append(f"code_solution_{lang}")
                    break

        return diff_fields

    def sync_problem(self, parsed: ParsedProblem, dry_run: bool = False) -> dict[str, Any]:
        """Atomically synchronize a single parsed problem into RDS PostgreSQL.

        Args:
            parsed: Parsed problem instance.
            dry_run: When True, simulates synchronization without modifying the database.

        Returns:
            dict with keys: 'status' ('added'|'updated'|'unchanged'|'error'), 'qnum', 'title', 'details'.
        """
        is_valid, reason = validate_problem(parsed)
        if not is_valid:
            return {
                "status": "error",
                "qnum": getattr(parsed, "qnum", 0),
                "title": getattr(parsed, "title", ""),
                "details": f"Validation failed: {reason}",
            }

        conn = None
        try:
            with self._get_connection() as conn:
                try:
                    from psycopg2.extras import RealDictCursor
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                except Exception:
                    cursor = conn.cursor()

                try:
                    # 1. Resolve slug collision if slug belongs to another qnum
                    target_slug = self._resolve_slug(cursor, parsed)

                    # 2. Query existing problem record
                    cursor.execute(
                        """
                        SELECT qnum, title, slug, difficulty, topic_tags, description_md
                        FROM public.leetcode_problems
                        WHERE qnum = %s;
                        """,
                        (parsed.qnum,),
                    )
                    raw_existing = cursor.fetchone()
                    existing_prob = _dict_row(cursor, raw_existing)

                    diff_fields: list[str] = []
                    if existing_prob:
                        diff_fields = self._compare_existing(
                            cursor, parsed, target_slug, existing_prob
                        )

                    # 3. Dry-run handling
                    if dry_run:
                        if not existing_prob:
                            return {
                                "status": "added",
                                "qnum": parsed.qnum,
                                "title": parsed.title,
                                "details": "Problem does not exist in database, would be inserted.",
                            }
                        if diff_fields:
                            return {
                                "status": "updated",
                                "qnum": parsed.qnum,
                                "title": parsed.title,
                                "details": f"Differences detected in: {', '.join(diff_fields)}.",
                            }
                        return {
                            "status": "unchanged",
                            "qnum": parsed.qnum,
                            "title": parsed.title,
                            "details": "All fields, approaches, and code solutions are identical.",
                        }

                    # 4. Actual synchronization mutations inside atomic transaction
                    action_status = "added" if not existing_prob else ("updated" if diff_fields else "unchanged")

                    # Upsert problem master record
                    upsert_problem_sql = """
                    INSERT INTO public.leetcode_problems (
                        qnum, title, slug, difficulty, topic_tags, description_md, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, now()
                    )
                    ON CONFLICT (qnum) DO UPDATE SET
                        title = EXCLUDED.title,
                        slug = EXCLUDED.slug,
                        difficulty = EXCLUDED.difficulty,
                        topic_tags = EXCLUDED.topic_tags,
                        description_md = EXCLUDED.description_md,
                        updated_at = now();
                    """
                    cursor.execute(
                        upsert_problem_sql,
                        (
                            parsed.qnum,
                            parsed.title,
                            target_slug,
                            parsed.difficulty,
                            parsed.topic_tags,
                            parsed.description_md,
                        ),
                    )

                    # Upsert approaches
                    upsert_approach_sql = """
                    INSERT INTO public.leetcode_approaches (
                        qnum, approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (qnum, approach_index) DO UPDATE SET
                        title = EXCLUDED.title,
                        intuition_md = EXCLUDED.intuition_md,
                        time_complexity = EXCLUDED.time_complexity,
                        space_complexity = EXCLUDED.space_complexity,
                        explanation_md = EXCLUDED.explanation_md;
                    """
                    for app in parsed.approaches:
                        cursor.execute(
                            upsert_approach_sql,
                            (
                                parsed.qnum,
                                app.approach_index,
                                app.title,
                                app.intuition_md,
                                app.time_complexity,
                                app.space_complexity,
                                app.explanation_md,
                            ),
                        )

                    # Delete obsolete approaches
                    if parsed.approaches:
                        cursor.execute(
                            "DELETE FROM public.leetcode_approaches WHERE qnum = %s AND approach_index > %s;",
                            (parsed.qnum, len(parsed.approaches)),
                        )
                    else:
                        cursor.execute(
                            "DELETE FROM public.leetcode_approaches WHERE qnum = %s;",
                            (parsed.qnum,),
                        )

                    # Upsert code solutions
                    upsert_solution_sql = """
                    INSERT INTO public.leetcode_code_solutions (
                        qnum, language, code_content
                    ) VALUES (
                        %s, %s, %s
                    )
                    ON CONFLICT (qnum, language) DO UPDATE SET
                        code_content = EXCLUDED.code_content;
                    """
                    for lang, code in parsed.code_solutions.items():
                        cursor.execute(
                            upsert_solution_sql,
                            (parsed.qnum, lang, code),
                        )

                    # Delete obsolete code solutions
                    if parsed.code_solutions:
                        cursor.execute(
                            "DELETE FROM public.leetcode_code_solutions WHERE qnum = %s AND NOT (language = ANY(%s));",
                            (parsed.qnum, list(parsed.code_solutions.keys())),
                        )
                    else:
                        cursor.execute(
                            "DELETE FROM public.leetcode_code_solutions WHERE qnum = %s;",
                            (parsed.qnum,),
                        )

                    conn.commit()

                    details = (
                        f"Problem successfully inserted (qnum={parsed.qnum})."
                        if action_status == "added"
                        else (
                            f"Problem successfully updated (diffs: {', '.join(diff_fields)})."
                            if action_status == "updated"
                            else "Problem already in sync; timestamps updated."
                        )
                    )
                    return {
                        "status": action_status,
                        "qnum": parsed.qnum,
                        "title": parsed.title,
                        "details": details,
                    }

                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass

        except Exception as exc:
            logger.error(
                "Error synchronizing problem %d (%s): %s",
                getattr(parsed, "qnum", 0),
                getattr(parsed, "title", ""),
                exc,
                exc_info=True,
            )
            if conn and not getattr(conn, "closed", False):
                try:
                    conn.rollback()
                except Exception:
                    pass
            return {
                "status": "error",
                "qnum": getattr(parsed, "qnum", 0),
                "title": getattr(parsed, "title", ""),
                "details": str(exc),
            }

    def get_delivery_status(self, delivery_id: str) -> Optional[str]:
        """Retrieve current processing status for a delivery ID from leetcode_sync_history."""
        sql = "SELECT status FROM public.leetcode_sync_history WHERE delivery_id = %s;"
        row = self._execute_query(sql, (delivery_id,), fetch="one")
        if row and row.get("status"):
            return str(row["status"])
        return None

    def record_sync_start(
        self, delivery_id: str, commit_sha: str, repo: str, branch: str
    ) -> None:
        """Record the start of a synchronization pipeline run in leetcode_sync_history.

        Preserves existing terminal 'success' status if a duplicate delivery arrives.
        """
        sql = """
        INSERT INTO public.leetcode_sync_history (
            delivery_id, source_repo, source_branch, commit_sha, status,
            files_processed, files_added, files_updated, files_ignored, files_failed,
            error_summary, created_at
        ) VALUES (
            %s, %s, %s, %s, 'in_progress', 0, 0, 0, 0, 0, '', now()
        )
        ON CONFLICT (delivery_id) DO UPDATE SET
            source_repo = EXCLUDED.source_repo,
            source_branch = EXCLUDED.source_branch,
            commit_sha = EXCLUDED.commit_sha,
            status = CASE
                WHEN public.leetcode_sync_history.status = 'success' THEN public.leetcode_sync_history.status
                ELSE 'in_progress'
            END,
            created_at = CASE
                WHEN public.leetcode_sync_history.status = 'success' THEN public.leetcode_sync_history.created_at
                ELSE now()
            END;
        """
        self._execute_mutation(sql, (delivery_id, repo, branch, commit_sha))

    def record_sync_completion(
        self,
        delivery_id: str,
        commit_sha: str,
        status: str,
        files_processed: int,
        files_added: int,
        files_updated: int,
        files_ignored: int,
        files_failed: int,
        error_summary: str = "",
        repo: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> None:
        """Record the completion of a synchronization pipeline run and update commit state."""
        update_history_sql = """
        UPDATE public.leetcode_sync_history SET
            status = %s,
            commit_sha = %s,
            files_processed = %s,
            files_added = %s,
            files_updated = %s,
            files_ignored = %s,
            files_failed = %s,
            error_summary = %s,
            completed_at = now()
        WHERE delivery_id = %s;
        """
        self._execute_mutation(
            update_history_sql,
            (
                status,
                commit_sha,
                files_processed,
                files_added,
                files_updated,
                files_ignored,
                files_failed,
                error_summary,
                delivery_id,
            ),
        )

        if status == "success":
            # If repo/branch were not supplied, look them up from history
            if not repo or not branch:
                row = self._execute_query(
                    "SELECT source_repo, source_branch FROM public.leetcode_sync_history WHERE delivery_id = %s;",
                    (delivery_id,),
                    fetch="one",
                )
                if row:
                    repo = repo or row.get("source_repo")
                    branch = branch or row.get("source_branch")

            if repo and branch:
                upsert_state_sql = """
                INSERT INTO public.leetcode_sync_state (
                    source_repo, source_branch, last_sync_commit_sha, last_sync_timestamp, updated_at
                ) VALUES (
                    %s, %s, %s, now(), now()
                )
                ON CONFLICT (source_repo, source_branch) DO UPDATE SET
                    last_sync_commit_sha = EXCLUDED.last_sync_commit_sha,
                    last_sync_timestamp = now(),
                    updated_at = now();
                """
                self._execute_mutation(upsert_state_sql, (repo, branch, commit_sha))

    def get_last_sync_sha(self, repo: str, branch: str) -> Optional[str]:
        """Retrieve the last successfully synchronized commit SHA for a repository and branch."""
        sql = """
        SELECT last_sync_commit_sha
        FROM public.leetcode_sync_state
        WHERE source_repo = %s AND source_branch = %s;
        """
        row = self._execute_query(sql, (repo, branch), fetch="one")
        if row and row.get("last_sync_commit_sha"):
            return str(row["last_sync_commit_sha"])
        return None

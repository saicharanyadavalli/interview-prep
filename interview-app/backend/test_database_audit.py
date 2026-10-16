"""Comprehensive database audit test script against live Supabase.
Tests every query, column projection, filter, order, and mutation.
"""

import sys
import os
import json
import traceback
from pathlib import Path
from dotenv import load_dotenv

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

load_dotenv(backend_dir / ".env")

from services.supabase_client import get_supabase_client

client = get_supabase_client()

results = []

def test(name, fn):
    try:
        res = fn()
        results.append({"test": name, "status": "PASS", "details": res})
        print(f"[PASS] {name}")
    except Exception as e:
        results.append({
            "test": name,
            "status": "FAIL",
            "error": str(e),
            "traceback": traceback.format_exc()
        })
        print(f"[FAIL] {name}: {e}")

# ----------------------------------------------------
# 1. question_bank_questions & question_bank_qnum_aliases
# ----------------------------------------------------
print("--- Auditing question_bank_questions & aliases ---")

def test_qb_sample():
    res = client.table("question_bank_questions").select("*").limit(2).execute()
    data = res.data or []
    diffs = [r.get("difficulty") for r in data]
    return {"sample_count": len(data), "sample_difficulties": diffs}
test("QB Questions: select * limit 2", test_qb_sample)

def test_qb_distinct_difficulties():
    # Check distinct values of difficulty in question_bank_questions
    res = client.table("question_bank_questions").select("difficulty").limit(500).execute()
    diffs = list({r.get("difficulty") for r in (res.data or [])})
    return {"difficulties": diffs}
test("QB Questions: distinct difficulties sample", test_qb_distinct_difficulties)

def test_qb_catalog_select():
    # This exact query is used in _db_fetch_catalog_rows()
    batch = (
        client.table("question_bank_questions")
        .select(
            "qnum,question_id,problem_name,difficulty,problem_url,"
            "statement_text,constraints_text,examples,topic_tags,"
            "company_tags,raw,primary_company,companies,company_count,source_qnums"
        )
        .order("qnum")
        .range(0, 5)
        .execute()
    )
    return {"count": len(batch.data or []), "first_qnum": batch.data[0]["qnum"] if batch.data else None}
test("QB Questions: _db_fetch_catalog_rows projection", test_qb_catalog_select)

def test_qb_filter_company_difficulty():
    # Test _db_fetch_questions_for_company_difficulty query
    # What happens when we query .eq("difficulty", "easy") vs "Easy"?
    batch_lower = (
        client.table("question_bank_questions")
        .select("qnum,difficulty,company_tags")
        .eq("difficulty", "easy")
        .limit(10)
        .execute()
    )
    batch_cap = (
        client.table("question_bank_questions")
        .select("qnum,difficulty,company_tags")
        .eq("difficulty", "Easy")
        .limit(10)
        .execute()
    )
    return {
        "count_easy_lowercase": len(batch_lower.data or []),
        "count_Easy_capitalized": len(batch_cap.data or [])
    }
test("QB Questions: difficulty case sensitivity (easy vs Easy)", test_qb_filter_company_difficulty)

def test_qb_qnum_by_question_id():
    # Test find_qnum_by_question_id
    # First get a valid question_id
    sample = client.table("question_bank_questions").select("question_id, qnum").limit(1).execute()
    if not sample.data:
        return "No rows"
    qid = sample.data[0]["question_id"]
    row = (
        client.table("question_bank_questions")
        .select("qnum")
        .eq("question_id", qid)
        .limit(1)
        .execute()
    ).data
    return {"question_id": qid, "found_qnum": row[0]["qnum"] if row else None}
test("QB Questions: find_qnum_by_question_id query", test_qb_qnum_by_question_id)

def test_qb_aliases():
    # Test question_bank_qnum_aliases
    sample = client.table("question_bank_qnum_aliases").select("*").limit(3).execute()
    return {"sample": sample.data}
test("QB Aliases: select * limit 3", test_qb_aliases)

# ----------------------------------------------------
# 2. leetcode_problems, leetcode_approaches, leetcode_code_solutions
# ----------------------------------------------------
print("\n--- Auditing LeetCode DSA tables ---")

def test_lc_problems_query():
    # Test get_leetcode_problems query
    res = client.table("leetcode_problems").select(
        "qnum, title, slug, difficulty, rating, topic_tags", count="exact"
    ).order("qnum", desc=False).range(0, 5).execute()
    return {"total": res.count, "returned": len(res.data or []), "first": res.data[0] if res.data else None}
test("LeetCode problems: basic list query with count", test_lc_problems_query)

def test_lc_difficulty_values():
    res = client.table("leetcode_problems").select("difficulty").limit(50).execute()
    diffs = list({r.get("difficulty") for r in (res.data or [])})
    return {"difficulties": diffs}
test("LeetCode problems: distinct difficulties", test_lc_difficulty_values)

def test_lc_topic_tags_type():
    res = client.table("leetcode_problems").select("topic_tags").limit(5).execute()
    types = [type(r.get("topic_tags")).__name__ for r in (res.data or [])]
    return {"types": types, "sample": [r.get("topic_tags") for r in (res.data or [])]}
test("LeetCode problems: topic_tags column type (JSON vs text vs array)", test_lc_topic_tags_type)

def test_lc_problem_detail():
    # Test get_leetcode_problem_detail
    res = client.table("leetcode_problems").select("*").eq("qnum", 1).limit(1).execute()
    return {"found": bool(res.data), "keys": list(res.data[0].keys()) if res.data else []}
test("LeetCode problems: detail by qnum=1", test_lc_problem_detail)

def test_lc_approaches():
    res = client.table("leetcode_approaches").select("*").eq("qnum", 1).order("approach_index", desc=False).execute()
    return {"count": len(res.data or []), "keys": list(res.data[0].keys()) if res.data else []}
test("LeetCode approaches: approaches for qnum=1", test_lc_approaches)

def test_lc_code_solutions():
    res = client.table("leetcode_code_solutions").select("language, code_content").eq("qnum", 1).order("language", desc=False).execute()
    langs = [r.get("language") for r in (res.data or [])]
    return {"count": len(res.data or []), "languages": langs}
test("LeetCode code solutions: solutions for qnum=1", test_lc_code_solutions)

# ----------------------------------------------------
# 3. course_lessons & learning_track_progress
# ----------------------------------------------------
print("\n--- Auditing Course Lessons & Learning Track Progress ---")

def test_course_lessons_track_ids():
    res = client.table("course_lessons").select("track_id").execute()
    distinct_tracks = {}
    for r in (res.data or []):
        t = r.get("track_id")
        distinct_tracks[t] = distinct_tracks.get(t, 0) + 1
    return {"track_id_counts": distinct_tracks}
test("Course lessons: distinct track_ids and counts", test_course_lessons_track_ids)

def test_course_lessons_sample():
    res = client.table("course_lessons").select("id, track_id, step_no, title").limit(5).execute()
    return {"sample": res.data}
test("Course lessons: sample rows", test_course_lessons_sample)

def test_course_lessons_detail_query():
    # Test fetch_lesson_detail query: eq("track_id", norm_slug).eq("step_no", step_no)
    res = (
        client.table("course_lessons")
        .select("id, track_id, step_no, title, html_content")
        .eq("track_id", "system-design")
        .eq("step_no", 1)
        .limit(1)
        .execute()
    )
    return {"found": bool(res.data), "title": res.data[0]["title"] if res.data else None}
test("Course lessons: fetch step 1 for system-design", test_course_lessons_detail_query)

def test_learning_track_progress_upsert():
    # Test upsert on learning_track_progress with on_conflict="user_id,track_id,step_no"
    # Use a dummy test user_id
    dummy_uid = "00000000-0000-0000-0000-000000000001"
    try:
        res = client.table("learning_track_progress").upsert(
            {
                "user_id": dummy_uid,
                "track_id": "system-design",
                "step_no": 999,
                "completed": True,
            },
            on_conflict="user_id,track_id,step_no"
        ).execute()
        # Clean up
        client.table("learning_track_progress").delete().eq("user_id", dummy_uid).eq("step_no", 999).execute()
        return {"status": "upsert_succeeded", "data": res.data}
    except Exception as e:
        raise e
test("Learning track progress: upsert with on_conflict='user_id,track_id,step_no'", test_learning_track_progress_upsert)

# ----------------------------------------------------
# 4. user_profiles & public.users table check
# ----------------------------------------------------
print("\n--- Auditing user_profiles & public.users ---")

def test_public_users_table():
    try:
        res = client.table("users").select("*").limit(1).execute()
        return {"exists": True, "count": len(res.data or [])}
    except Exception as e:
        return {"exists": False, "error": str(e)}
test("Check public.users table existence", test_public_users_table)

def test_user_profiles_select():
    res = client.table("user_profiles").select("id,email,username,name,phone,avatar_url").limit(3).execute()
    return {"count": len(res.data or []), "sample": res.data}
test("User profiles: select fields", test_user_profiles_select)

def test_user_profiles_upsert():
    dummy_uid = "00000000-0000-0000-0000-000000000002"
    payload = {
        "id": dummy_uid,
        "email": "audit_test@example.com",
        "username": "audit_test",
        "name": "Audit Test",
        "phone": "1234567890",
        "avatar_url": "",
    }
    try:
        res = client.table("user_profiles").upsert(payload, on_conflict="id").execute()
        # Clean up
        client.table("user_profiles").delete().eq("id", dummy_uid).execute()
        return {"status": "upsert_succeeded"}
    except Exception as e:
        raise e
test("User profiles: upsert on_conflict='id'", test_user_profiles_upsert)

# ----------------------------------------------------
# 5. user_progress & practice_history
# ----------------------------------------------------
print("\n--- Auditing user_progress & practice_history ---")

def test_user_progress_upsert():
    dummy_uid = "00000000-0000-0000-0000-000000000003"
    payload = {
        "user_id": dummy_uid,
        "qnum": 999999,
        "is_solved": True,
        "is_revisit": False,
    }
    try:
        res = client.table("user_progress").upsert(payload, on_conflict="user_id,qnum").execute()
        # Clean up
        client.table("user_progress").delete().eq("user_id", dummy_uid).eq("qnum", 999999).execute()
        return {"status": "upsert_succeeded"}
    except Exception as e:
        raise e
test("User progress: upsert with on_conflict='user_id,qnum'", test_user_progress_upsert)

def test_practice_history_insert():
    dummy_uid = "00000000-0000-0000-0000-000000000004"
    payload = {
        "user_id": dummy_uid,
        "qnum": 999999,
    }
    try:
        res = client.table("practice_history").insert(payload).execute()
        inserted_id = res.data[0]["id"] if res.data else None
        # Clean up
        if inserted_id:
            client.table("practice_history").delete().eq("id", inserted_id).execute()
        return {"status": "insert_succeeded", "id": inserted_id}
    except Exception as e:
        raise e
test("Practice history: insert without explicit id", test_practice_history_insert)

# ----------------------------------------------------
# 6. user_comments
# ----------------------------------------------------
print("\n--- Auditing user_comments ---")

def test_user_comments_crud():
    dummy_uid = "00000000-0000-0000-0000-000000000005"
    try:
        # Insert
        ins = client.table("user_comments").insert({
            "user_id": dummy_uid,
            "qnum": 999999,
            "comment_text": "Audit test comment"
        }).execute()
        cid = ins.data[0]["id"] if ins.data else None
        
        # Select
        sel = client.table("user_comments").select("*").eq("user_id", dummy_uid).eq("qnum", 999999).execute()
        
        # Update
        upd = client.table("user_comments").update({"comment_text": "Updated audit comment"}).eq("id", cid).execute()
        
        # Delete
        dele = client.table("user_comments").delete().eq("id", cid).execute()
        
        return {"inserted_id": cid, "found_count": len(sel.data or []), "delete_count": len(dele.data or [])}
    except Exception as e:
        raise e
test("User comments: Insert, Select, Update, Delete cycle", test_user_comments_crud)

# Write full results to json
with open(backend_dir / "audit_test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nAudit completed. Results saved to audit_test_results.json")

"""Audit script testing service functions and router logic against live Supabase."""

import sys
import os
import json
import traceback
from pathlib import Path
from dotenv import load_dotenv

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

load_dotenv(backend_dir / ".env")

from services.rds_client import rds_client
from services.questions_service import (
    get_companies,
    get_all_questions,
    get_random_question,
    get_recommended_question,
    get_all_questions_catalog,
    get_question_by_qnum,
    find_qnum_by_question_id,
    get_question_summary_by_qnum,
)
from services.courses_service import (
    fetch_all_courses,
    fetch_course_by_slug,
    fetch_lesson_detail,
    record_lesson_completion,
    fetch_course_user_progress,
)
from routes.leetcode import (
    get_leetcode_problems,
    get_leetcode_problem_detail,
    get_leetcode_problem_approaches,
    get_leetcode_problem_code,
)

results = {}

print("=== 1. Testing questions_service ===")

try:
    companies = get_companies()
    results["get_companies"] = {
        "status": "PASS",
        "count": len(companies),
        "first_5": companies[:5] if companies else []
    }
    print(f"[PASS] get_companies(): {len(companies)} companies found. Sample: {companies[:3]}")
except Exception as e:
    results["get_companies"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_companies(): {e}")

try:
    first_company = companies[0] if companies else "Amazon"
    q_all = get_all_questions(first_company, "easy")
    results["get_all_questions"] = {
        "status": "PASS",
        "company": first_company,
        "difficulty": "easy",
        "count": len(q_all),
        "first_qnum": q_all[0]["qnum"] if q_all else None
    }
    print(f"[PASS] get_all_questions({first_company}, easy): {len(q_all)} questions returned.")
except Exception as e:
    results["get_all_questions"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_all_questions(): {e}")

try:
    q_rand = get_random_question(first_company, "easy")
    results["get_random_question"] = {
        "status": "PASS",
        "found": q_rand is not None,
        "qnum": q_rand["qnum"] if q_rand else None
    }
    print(f"[PASS] get_random_question(): {q_rand.get('problem_name') if q_rand else None}")
except Exception as e:
    results["get_random_question"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_random_question(): {e}")

try:
    catalog = get_all_questions_catalog()
    results["get_all_questions_catalog"] = {
        "status": "PASS",
        "count": len(catalog),
        "sample": catalog[0] if catalog else None
    }
    print(f"[PASS] get_all_questions_catalog(): {len(catalog)} questions in catalog.")
except Exception as e:
    results["get_all_questions_catalog"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_all_questions_catalog(): {e}")

try:
    q1 = get_question_by_qnum(1)
    results["get_question_by_qnum_1"] = {
        "status": "PASS",
        "found": q1 is not None,
        "name": q1.get("problem_name") if q1 else None
    }
    print(f"[PASS] get_question_by_qnum(1): {q1.get('problem_name') if q1 else 'NOT FOUND'}")
except Exception as e:
    results["get_question_by_qnum_1"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_question_by_qnum(1): {e}")

try:
    s1 = get_question_summary_by_qnum(1)
    results["get_question_summary_by_qnum_1"] = {
        "status": "PASS",
        "summary": s1
    }
    print(f"[PASS] get_question_summary_by_qnum(1): {s1}")
except Exception as e:
    results["get_question_summary_by_qnum_1"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_question_summary_by_qnum(1): {e}")

print("\n=== 2. Testing courses_service ===")

try:
    # Test fetch_all_courses without user
    courses = fetch_all_courses(user_id=None)
    results["fetch_all_courses_anon"] = {
        "status": "PASS",
        "count": len(courses),
        "courses": [{"slug": c["slug"], "total_lessons": c["total_lessons"]} for c in courses]
    }
    print(f"[PASS] fetch_all_courses(user_id=None): {len(courses)} courses.")
    for c in courses:
        print(f"  - {c['slug']}: {c['total_lessons']} lessons")
except Exception as e:
    results["fetch_all_courses_anon"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] fetch_all_courses(): {e}")

# Check with real user from RDS user_profiles
real_user_res = rds_client.query("SELECT id FROM user_profiles LIMIT 1;", fetch="one")
real_uid = str(real_user_res["id"]) if real_user_res else None

if real_uid:
    try:
        courses_user = fetch_all_courses(user_id=real_uid)
        results["fetch_all_courses_user"] = {
            "status": "PASS",
            "user_id": real_uid,
            "courses": [{"slug": c["slug"], "completed": c["completed_lessons"], "total": c["total_lessons"]} for c in courses_user]
        }
        print(f"[PASS] fetch_all_courses(user_id={real_uid}): succeeded.")
    except Exception as e:
        results["fetch_all_courses_user"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
        print(f"[FAIL] fetch_all_courses(user): {e}")

try:
    # Test fetch_course_by_slug for all known slugs
    slugs = ["system-design", "genai-system-design", "ml-system-design", "mobile-system-design", "object-oriented-design", "sql-course"]
    course_details = {}
    for s in slugs:
        cd = fetch_course_by_slug(s, user_id=None)
        course_details[s] = {
            "found": cd is not None,
            "total_lessons": cd.get("total_lessons") if cd else 0,
            "lesson_count": len(cd.get("lessons", [])) if cd else 0,
            "first_lesson_title": cd["lessons"][0]["title"] if cd and cd.get("lessons") else None
        }
    results["fetch_course_by_slug"] = {"status": "PASS", "details": course_details}
    print(f"[PASS] fetch_course_by_slug for all tracks: {course_details}")
except Exception as e:
    results["fetch_course_by_slug"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] fetch_course_by_slug: {e}")

try:
    # Test fetch_lesson_detail
    ld = fetch_lesson_detail("system-design", "step-1", user_id=None)
    results["fetch_lesson_detail_system_design_1"] = {
        "status": "PASS",
        "found": ld is not None,
        "title": ld.get("title") if ld else None,
        "content_len": len(ld.get("content_markdown", "")) if ld else 0,
        "prev": ld.get("prev_lesson_slug") if ld else None,
        "next": ld.get("next_lesson_slug") if ld else None,
    }
    print(f"[PASS] fetch_lesson_detail(system-design, step-1): title='{ld.get('title') if ld else None}', content_len={len(ld.get('content_markdown', '')) if ld else 0}")
except Exception as e:
    results["fetch_lesson_detail_system_design_1"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] fetch_lesson_detail: {e}")

# Test record_lesson_completion with real user
if real_uid:
    try:
        rec = record_lesson_completion(user_id=real_uid, course_slug="system-design", lesson_slug="step-999", completed=True)
        # Verify and clean up
        rds_client.mutate("DELETE FROM learning_track_progress WHERE user_id = %s AND step_no = %s;", (real_uid, 999))
        results["record_lesson_completion"] = {
            "status": "PASS",
            "rec": rec
        }
        print(f"[PASS] record_lesson_completion with real user: {rec.get('success')}")
    except Exception as e:
        results["record_lesson_completion"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
        print(f"[FAIL] record_lesson_completion: {e}")

print("\n=== 3. Testing leetcode router ===")

try:
    # Test without filters
    res = get_leetcode_problems(page=1, limit=10)
    results["leetcode_problems_no_filter"] = {
        "status": "PASS",
        "total": res.total,
        "count": len(res.problems),
        "first": res.problems[0].dict() if res.problems else None
    }
    print(f"[PASS] get_leetcode_problems(page=1, limit=10): total={res.total}, returned={len(res.problems)}")
except Exception as e:
    results["leetcode_problems_no_filter"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_leetcode_problems: {e}")

try:
    # Test with difficulty="Medium"
    res_med = get_leetcode_problems(page=1, limit=10, difficulty="Medium")
    results["leetcode_problems_difficulty_Medium"] = {
        "status": "PASS",
        "total": res_med.total,
        "count": len(res_med.problems),
        "all_medium": all(p.difficulty == "Medium" for p in res_med.problems)
    }
    print(f"[PASS] get_leetcode_problems(difficulty=Medium): total={res_med.total}, all_medium={results['leetcode_problems_difficulty_Medium']['all_medium']}")
except Exception as e:
    results["leetcode_problems_difficulty_Medium"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_leetcode_problems(difficulty=Medium): {e}")

try:
    # Test with tag="Array"
    res_tag = get_leetcode_problems(page=1, limit=10, tag="Array")
    has_tag = [("Array" in p.topic_tags) for p in res_tag.problems]
    results["leetcode_problems_tag_Array"] = {
        "status": "PASS",
        "total": res_tag.total,
        "count": len(res_tag.problems),
        "has_tag_Array_rate": f"{sum(has_tag)}/{len(has_tag)}",
        "all_have_Array": all(has_tag)
    }
    print(f"[RESULT] get_leetcode_problems(tag=Array): total={res_tag.total}, problems containing Array: {sum(has_tag)}/{len(has_tag)}")
except Exception as e:
    results["leetcode_problems_tag_Array"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_leetcode_problems(tag=Array): {e}")

try:
    detail = get_leetcode_problem_detail(qnum=1)
    results["leetcode_problem_detail_1"] = {"status": "PASS", "title": detail.get("title")}
    print(f"[PASS] get_leetcode_problem_detail(1): {detail.get('title')}")
except Exception as e:
    results["leetcode_problem_detail_1"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_leetcode_problem_detail(1): {e}")

try:
    approaches = get_leetcode_problem_approaches(qnum=1)
    results["leetcode_problem_approaches_1"] = {"status": "PASS", "count": len(approaches)}
    print(f"[PASS] get_leetcode_problem_approaches(1): {len(approaches)} approaches")
except Exception as e:
    results["leetcode_problem_approaches_1"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_leetcode_problem_approaches(1): {e}")

try:
    code = get_leetcode_problem_code(qnum=1)
    results["leetcode_problem_code_1"] = {"status": "PASS", "languages": code.get("languages", [])}
    print(f"[PASS] get_leetcode_problem_code(1): {len(code.get('languages', []))} languages")
except Exception as e:
    results["leetcode_problem_code_1"] = {"status": "FAIL", "error": str(e), "tb": traceback.format_exc()}
    print(f"[FAIL] get_leetcode_problem_code(1): {e}")

# Save results
with open(backend_dir / "services_audit_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nSaved services audit results to services_audit_results.json")

"""Direct endpoint testing script against live Supabase."""

import sys
import os
import json
import traceback
from pathlib import Path
from dotenv import load_dotenv

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

load_dotenv(backend_dir / ".env")

from fastapi.testclient import TestClient
from main import app
from services.rds_client import rds_client

client = TestClient(app)

# Fetch a user from RDS user_profiles to test authenticated endpoints
try:
    real_user = rds_client.query("SELECT id, email, username FROM user_profiles LIMIT 1;", fetch="one")
except Exception:
    real_user = None
print(f"Testing with user: {real_user}")

# Mock auth dependency or disable auth for test
from routes.auth import get_current_user, get_optional_current_user

def mock_get_current_user():
    return {
        "id": real_user["id"] if real_user else "d3720441-afd9-4dda-afac-ec216cbdcf66",
        "email": real_user["email"] if real_user else "portaluser88@gmail.com",
        "username": real_user["username"] if real_user else "portal_user88",
        "name": "Test User",
        "avatar_url": "",
    }

def mock_get_optional_current_user():
    return mock_get_current_user()

app.dependency_overrides[get_current_user] = mock_get_current_user
app.dependency_overrides[get_optional_current_user] = mock_get_optional_current_user

tests = [
    # Questions
    ("GET", "/questions/companies"),
    ("GET", "/questions/random?company=Amazon&difficulty=easy"),
    ("GET", "/questions/recommend?company=Amazon&difficulty=easy"),
    ("GET", "/questions/all?company=Amazon&difficulty=easy"),
    ("GET", "/questions/catalog?limit=5"),
    ("GET", "/questions/catalog?solved=solved&limit=5"),
    
    # Courses
    ("GET", "/courses"),
    ("GET", "/courses/system-design"),
    ("GET", "/courses/system-design/seed-tables"),
    ("GET", "/courses/system-design/lessons/step-1"),
    ("GET", "/courses/system-design/progress"),
    ("POST", "/courses/system-design/lessons/step-1/complete", {"completed": True}),
    
    # LeetCode
    ("GET", "/leetcode/problems?page=1&limit=5"),
    ("GET", "/leetcode/problems?page=1&limit=5&difficulty=Easy"),
    ("GET", "/leetcode/problems?page=1&limit=5&tag=Array"),
    ("GET", "/leetcode/problems?page=1&limit=5&search=Two%20Sum"),
    ("GET", "/leetcode/problems/1"),
    ("GET", "/leetcode/problems/1/approaches"),
    ("GET", "/leetcode/problems/1/code"),
    ("GET", "/leetcode/problems/1/code?language=python"),
    
    # Profile
    ("GET", "/profile/me"),
    ("PUT", "/profile/me", {"name": "Test User Updated"}),
    
    # Progress
    ("POST", "/progress/update", {"qnum": 1, "is_solved": True}),
    ("GET", "/progress/user"),
    ("GET", "/progress/user?summary_only=true"),
    ("GET", "/progress/status/1"),
    ("DELETE", "/progress/1"),
    
    # Revisit
    ("POST", "/progress/update", {"qnum": 1, "revisit": True}),
    ("GET", "/revisit"),
    ("DELETE", "/revisit/1"),
    
    # Comments
    ("POST", "/comments/add", {"qnum": 1, "comment_text": "Live test note"}),
    ("GET", "/comments/1"),
    
    # Learning Tracks (System Design)
    ("GET", "/learning-tracks"),
    ("GET", "/system-design/progress"),
    ("POST", "/system-design/progress/update", {"step_no": 1, "completed": True}),
]

results = []

for item in tests:
    method = item[0]
    path = item[1]
    payload = item[2] if len(item) > 2 else None
    
    try:
        if method == "GET":
            resp = client.get(path)
        elif method == "POST":
            resp = client.post(path, json=payload)
        elif method == "PUT":
            resp = client.put(path, json=payload)
        elif method == "DELETE":
            resp = client.delete(path)
            
        is_ok = 200 <= resp.status_code < 300
        status_label = "PASS" if is_ok else "FAIL"
        
        # Clean up comment if added
        if path == "/comments/1" and is_ok:
            data = resp.json()
            for c in data.get("comments", []):
                if c.get("comment_text") == "Live test note":
                    client.delete(f"/comments/{c['id']}")
                    
        print(f"[{status_label}] {method} {path} -> HTTP {resp.status_code}")
        if not is_ok:
            print(f"      Response: {resp.text[:300]}")
            
        results.append({
            "method": method,
            "path": path,
            "status_code": resp.status_code,
            "status": status_label,
            "response": resp.json() if "application/json" in resp.headers.get("content-type", "") else resp.text[:200]
        })
    except Exception as e:
        print(f"[FAIL] {method} {path} -> Exception: {e}")
        results.append({
            "method": method,
            "path": path,
            "status": "FAIL",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

with open(backend_dir / "endpoint_test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nSaved endpoint test results to endpoint_test_results.json")

"""
setup_database.py - Creates the required Supabase tables for the Interview Practice Platform.

Run this script once to set up all database tables:
    cd interview-app
    python setup_database.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load .env from project root
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SERVICE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    sys.exit(1)

project_ref = SUPABASE_URL.replace("https://", "").replace(".supabase.co", "")

print(f"Supabase project: {project_ref}")
print()

headers = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def table_exists(table_name):
    """Check if a table exists by trying to query it."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table_name}?limit=0",
        headers=headers,
    )
    return r.status_code == 200


# ----- Check existing tables -----
print("Checking existing tables...")
tables = ["user_progress", "practice_history", "user_comments"]

for t in tables:
    exists = table_exists(t)
    status = "[OK]" if exists else "[MISSING]"
    print(f"  {t}: {status}")

missing = [t for t in tables if not table_exists(t)]

if not missing:
    print("\nAll tables exist! Nothing to do.")
    sys.exit(0)

print(f"\nMissing tables: {', '.join(missing)}")
print()
print("="*60)
print("MANUAL SETUP REQUIRED")
print("="*60)
print()
print("Please do the following:")
print()
print("1. Open the Supabase SQL Editor:")
print(f"   https://supabase.com/dashboard/project/{project_ref}/sql/new")
print()
print("2. Copy ALL the SQL below and paste it into the editor")
print("3. Click 'Run' to execute")
print("4. Re-run this script to verify: python setup_database.py")
print()
print("="*60)
print("SQL TO COPY:")
print("="*60)
print()

sql_file = Path(__file__).parent / "supabase_setup.sql"
if sql_file.exists():
    print(sql_file.read_text(encoding="utf-8"))
else:
    print("-- ERROR: supabase_setup.sql not found!")

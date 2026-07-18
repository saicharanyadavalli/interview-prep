import os
import glob
import re
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent

# Load environment variables
load_dotenv(APP_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=False)

url = os.getenv("SUPABASE_URL", "").strip()
key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
if not url or not key:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

client = create_client(url, key)

FRONTEND_DIR = APP_DIR / "frontend"
COURSES = [
    "genai-system-design",
    "ml-system-design",
    "mobile-system-design",
    "object-oriented-design",
    "system-design"
]

rows = []
for course in COURSES:
    course_dir = FRONTEND_DIR / course / "lessons"
    if not course_dir.exists():
        print(f"Warning: {course_dir} does not exist.")
        continue
    
    for html_file in course_dir.glob("step-*.html"):
        step_match = re.search(r"step-(\d+)\.html", html_file.name)
        if not step_match:
            continue
        step_no = int(step_match.group(1))
        
        content = html_file.read_text(encoding="utf-8")
        title = "Untitled" # We can't easily extract title, but we can set it to step_no or parse
        
        # very simple title extraction if present
        title_match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
        if title_match:
            # strip tags if any
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
        else:
            title = f"Step {step_no}"
        
        rows.append({
            "track_id": course,
            "step_no": step_no,
            "title": title,
            "html_content": content
        })

print(f"Found {len(rows)} lessons. Uploading...")

# Upload in batches
BATCH_SIZE = 50
for i in range(0, len(rows), BATCH_SIZE):
    batch = rows[i:i + BATCH_SIZE]
    response = client.table("course_lessons").upsert(batch, on_conflict="track_id,step_no").execute()
    print(f"Uploaded batch of {len(batch)} lessons.")

print("Upload complete!")

import os
import re
import json
import sqlite3
import yaml
from pathlib import Path

SOLUTIONS_DIR = Path(r"C:\Users\yadav\Desktop\learning\leetcode data\solutions")
DB_PATH = Path(r"C:\Users\yadav\Desktop\learning\gfg crawler\interview-app\backend\leetcode_dsa.db")

def parse_markdown_file(filepath: Path):
    text = filepath.read_text(encoding='utf-8')
    
    # 1. Parse Frontmatter
    fm = {}
    body = text
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                fm = {}
            body = parts[2]

    # Extract Question Number and Title from filename or body header
    # e.g., "0001 - Two Sum.md"
    filename_match = re.match(r'^(\d+)\s*-\s*(.+)\.md$', filepath.name)
    if filename_match:
        qnum = int(filename_match.group(1))
        title = filename_match.group(2)
    else:
        qnum_title_m = re.search(r'#\s*\[(\d+)\.\s*([^\]]+)\]', body)
        if qnum_title_m:
            qnum = int(qnum_title_m.group(1))
            title = qnum_title_m.group(2)
        else:
            qnum = 0
            title = filepath.stem

    # Slug
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    difficulty = fm.get('difficulty', 'Easy')
    if difficulty not in ['Easy', 'Medium', 'Hard']:
        difficulty = 'Easy'
    
    tags = fm.get('tags', [])
    if isinstance(tags, str):
        tags = [tags]

    # 2. Extract Description Section
    desc_match = re.search(r'<!-- description:start -->(.*?)<!-- description:end -->', body, re.DOTALL)
    if desc_match:
        description_md = desc_match.group(1).strip()
    else:
        # Fallback to text before ## Solutions
        sol_split = body.split('## Solutions')
        description_md = sol_split[0].strip()

    # 3. Extract Solutions / Approaches & Code Snippets
    approaches = []
    code_solutions = {}

    sol_section_match = re.search(r'## Solutions(.*)', body, re.DOTALL)
    if sol_section_match:
        sol_text = sol_section_match.group(1)
        
        # Split by ### Solution N:
        sol_blocks = re.split(r'###\s+Solution\s+\d+:\s*', sol_text)
        for idx, block in enumerate(sol_blocks[1:], start=1):
            lines = block.strip().split('\n')
            approach_title = lines[0].strip() if lines else f"Approach {idx}"
            
            # Extract intuition / explanation text before <!-- tabs:start -->
            tabs_split = re.split(r'<!-- tabs:start -->', block)
            explanation_md = tabs_split[0].replace(lines[0], '', 1).strip() if len(tabs_split) > 0 else ""

            # Extract time & space complexity if available
            time_comp = ""
            space_comp = ""
            tc_m = re.search(r'Time complexity.*?(\$O\(.*?\)\$|O\(.*?\))', explanation_md, re.IGNORECASE)
            if tc_m:
                time_comp = tc_m.group(1)
            sc_m = re.search(r'Space complexity.*?(\$O\(.*?\)\$|O\(.*?\))', explanation_md, re.IGNORECASE)
            if sc_m:
                space_comp = sc_m.group(1)

            approaches.append({
                "approach_index": idx,
                "title": approach_title,
                "explanation_md": explanation_md,
                "time_complexity": time_comp,
                "space_complexity": space_comp
            })

            # Extract code tabs inside this solution
            if len(tabs_split) > 1:
                tab_content = tabs_split[1]
                # Match #### Language \n ```lang ... ```
                code_matches = re.findall(r'####\s+([^\n]+)\s*\n+```(\w+)?\n(.*?)```', tab_content, re.DOTALL)
                for lang_header, code_lang, code_text in code_matches:
                    lang_key = lang_header.strip().lower().replace(' ', '').replace('3', '')
                    if lang_key not in code_solutions:
                        code_solutions[lang_key] = code_text.strip()

    return {
        "qnum": qnum,
        "title": title,
        "slug": slug,
        "difficulty": difficulty,
        "tags": tags,
        "description_md": description_md,
        "approaches": approaches,
        "code_solutions": code_solutions
    }

def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create Option A Relational Tables in SQLite
    cur.execute("""
    CREATE TABLE IF NOT EXISTS leetcode_problems (
        qnum INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        slug TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        rating REAL DEFAULT NULL,
        topic_tags TEXT NOT NULL,
        company_tags TEXT NOT NULL DEFAULT '[]',
        description_md TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leetcode_approaches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        qnum INTEGER NOT NULL,
        approach_index INTEGER NOT NULL,
        title TEXT NOT NULL,
        intuition_md TEXT,
        time_complexity TEXT,
        space_complexity TEXT,
        explanation_md TEXT,
        FOREIGN KEY(qnum) REFERENCES leetcode_problems(qnum) ON DELETE CASCADE,
        UNIQUE(qnum, approach_index)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leetcode_code_solutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        qnum INTEGER NOT NULL,
        language TEXT NOT NULL,
        code_content TEXT NOT NULL,
        FOREIGN KEY(qnum) REFERENCES leetcode_problems(qnum) ON DELETE CASCADE,
        UNIQUE(qnum, language)
    );
    """)

    print("Parsing extracted solution files and populating SQLite database...")
    files = sorted(list(SOLUTIONS_DIR.glob("*.md")))
    print(f"Found {len(files)} markdown solution files.")

    prob_count = 0
    appr_count = 0
    code_count = 0

    for filepath in files:
        data = parse_markdown_file(filepath)
        if not data["qnum"]:
            continue

        # Insert problem
        cur.execute("""
        INSERT OR REPLACE INTO leetcode_problems 
        (qnum, title, slug, difficulty, rating, topic_tags, company_tags, description_md)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["qnum"],
            data["title"],
            data["slug"],
            data["difficulty"],
            None,
            json.dumps(data["tags"]),
            json.dumps([]),
            data["description_md"]
        ))
        prob_count += 1

        # Insert approaches
        for app in data["approaches"]:
            cur.execute("""
            INSERT OR REPLACE INTO leetcode_approaches 
            (qnum, approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data["qnum"],
                app["approach_index"],
                app["title"],
                "",
                app["time_complexity"],
                app["space_complexity"],
                app["explanation_md"]
            ))
            appr_count += 1

        # Insert code solutions
        for lang, code in data["code_solutions"].items():
            cur.execute("""
            INSERT OR REPLACE INTO leetcode_code_solutions (qnum, language, code_content)
            VALUES (?, ?, ?)
            """, (data["qnum"], lang, code))
            code_count += 1

    conn.commit()
    conn.close()

    print("\n--- Ingestion Complete ---")
    print(f"Total Problems Populated: {prob_count}")
    print(f"Total Approaches Populated: {appr_count}")
    print(f"Total Code Solutions Populated: {code_count}")
    print(f"Database File: {DB_PATH}")

if __name__ == "__main__":
    main()

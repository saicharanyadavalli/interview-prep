"""
add_question_numbers.py — Adds a global unique question number (qnum) to every JSON question.

Run once from the project root:
    cd interview-app
    python add_question_numbers.py

This reads all questions from output/stage3_company_wise/*/questions_detailed_{easy,medium,hard}.json,
assigns a stable global number (sorted by company alphabetically, then easy -> medium -> hard,
then by order in the file), and writes the qnum field back into each question JSON.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "output" / "stage3_company_wise"
DIFFICULTIES = ["easy", "medium", "hard"]


def main():
    if not BASE_DIR.exists():
        print(f"ERROR: Data directory not found: {BASE_DIR}")
        return

    # Collect all file paths in sorted order
    company_dirs = sorted([d for d in BASE_DIR.iterdir() if d.is_dir()], key=lambda d: d.name)

    qnum = 1  # Global counter starting at 1
    total_files = 0
    total_questions = 0

    for company_dir in company_dirs:
        for difficulty in DIFFICULTIES:
            file_path = company_dir / f"questions_detailed_{difficulty}.json"
            if not file_path.exists():
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, list):
                continue

            modified = False
            for item in data:
                if not isinstance(item, dict):
                    continue
                item["qnum"] = qnum
                qnum += 1
                modified = True

            if modified:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                total_files += 1
                total_questions += len(data)
                print(f"  {company_dir.name}/{difficulty}: {len(data)} questions (qnum {qnum - len(data)}-{qnum - 1})")

    print(f"\nDone! Assigned qnum 1-{qnum - 1} across {total_files} files ({total_questions} questions)")


if __name__ == "__main__":
    main()

import csv
import concurrent.futures
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.parse import parse_qs

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.geeksforgeeks.org/gfg-academy/company-preparation/"
OUTPUT_DIR = Path("output")
REQUEST_DELAY_SECONDS = 1.0
TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
PRACTICE_API_PROBLEMS_URL = "https://practiceapi.geeksforgeeks.org/api/v1/problems/"
PRACTICE_SITE_BASE_URL = "https://practice.geeksforgeeks.org"
STAGE2_LINKS_FILE = OUTPUT_DIR / "stage2_all_problem_links.json"
STAGE3_DELAY_SECONDS = 0.1
STAGE3_MAX_WORKERS = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

DIFFICULTY_PATTERN = re.compile(r"\b(easy|medium|hard)\b", re.IGNORECASE)
AVERAGE_TIME_PATTERN = re.compile(
    r"(?:avg(?:\.|erage)?\s*time\s*[:\-]?\s*)?"
    r"(\d+(?:\.\d+)?)\s*(mins?|minutes?|hrs?|hours?)",
    re.IGNORECASE,
)
def sanitize_name(name: str) -> str:
    sanitized = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip(" .")
    return sanitized or "unknown"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as error:
            last_error = error
            if attempt < MAX_RETRIES:
                time.sleep(1.0 * attempt)
            else:
                raise RuntimeError(f"Failed to fetch {url}: {error}") from error
    raise RuntimeError(f"Unexpected fetch failure for {url}: {last_error}")


def company_name_from_url(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        return "Unknown Company"
    return path_parts[-1].replace("-", " ").title()


def discover_company_links(session: requests.Session) -> List[Tuple[str, str]]:
    soup = fetch_soup(session, BASE_URL)
    company_links: Dict[str, str] = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if "company" not in href.lower():
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc != "www.geeksforgeeks.org":
            continue

        normalized_url = full_url.split("#")[0].rstrip("/") + "/"
        if normalized_url == BASE_URL.rstrip("/") + "/":
            continue

        query_company = parse_qs(parsed.query).get("company", [""])[0].strip()
        anchor_text = " ".join(anchor.get_text(" ", strip=True).split())
        company_name = query_company or anchor_text or company_name_from_url(normalized_url)

        if normalized_url not in company_links:
            company_links[normalized_url] = company_name

    return sorted(company_links.items(), key=lambda item: item[1].lower())


def parse_difficulty(text: str) -> Optional[str]:
    match = DIFFICULTY_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).title()


def parse_average_time(text: str) -> Optional[str]:
    match = AVERAGE_TIME_PATTERN.search(text)
    if not match:
        return None
    value = match.group(1)
    unit = match.group(2).lower()
    if unit.startswith("hr") or unit.startswith("hour"):
        unit = "hours"
    else:
        unit = "minutes"
    return f"{value} {unit}"


def extract_questions_from_rows(company_name: str, company_url: str, soup: BeautifulSoup) -> List[Dict[str, str]]:
    questions: Dict[str, Dict[str, str]] = {}

    for row in soup.find_all("tr"):
        row_text = " ".join(row.get_text(" ", strip=True).split())
        question_anchor = None
        for anchor in row.find_all("a", href=True):
            href = urljoin(company_url, anchor["href"].strip())
            if "/problems/" in href or "/practice" in href:
                question_anchor = anchor
                break

        if not question_anchor:
            continue

        question_name = " ".join(question_anchor.get_text(" ", strip=True).split())
        question_url = urljoin(company_url, question_anchor["href"].strip())
        difficulty = parse_difficulty(row_text)
        average_time = parse_average_time(row_text)

        if question_url not in questions:
            questions[question_url] = {
                "company": company_name,
                "company_url": company_url,
                "question": question_name or "Unknown Question",
                "question_url": question_url,
                "difficulty": difficulty or "Unknown",
                "average_time": average_time or "Unknown",
            }

    return list(questions.values())


def extract_questions_from_links(company_name: str, company_url: str, soup: BeautifulSoup) -> List[Dict[str, str]]:
    questions: Dict[str, Dict[str, str]] = {}

    for anchor in soup.find_all("a", href=True):
        href = urljoin(company_url, anchor["href"].strip())
        if "/problems/" not in href and "/practice" not in href:
            continue

        question_name = " ".join(anchor.get_text(" ", strip=True).split())
        if not question_name:
            continue

        context_node = anchor.find_parent(["tr", "li", "div", "section", "article"]) or anchor
        context_text = " ".join(context_node.get_text(" ", strip=True).split())
        difficulty = parse_difficulty(context_text)
        average_time = parse_average_time(context_text)

        if href not in questions:
            questions[href] = {
                "company": company_name,
                "company_url": company_url,
                "question": question_name,
                "question_url": href,
                "difficulty": difficulty or "Unknown",
                "average_time": average_time or "Unknown",
            }

    return list(questions.values())


def extract_questions_for_company(
    session: requests.Session, company_name: str, company_url: str
) -> List[Dict[str, str]]:
    soup = fetch_soup(session, company_url)
    row_based = extract_questions_from_rows(company_name, company_url, soup)
    if row_based:
        return row_based
    return extract_questions_from_links(company_name, company_url, soup)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "company",
        "company_url",
        "question",
        "question_url",
        "difficulty",
        "average_time",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_stage2_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "company",
        "company_explore_url",
        "problem_name",
        "problem_url",
        "difficulty",
        "page",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fetch_company_problem_links(
    session: requests.Session, company_name: str, company_explore_url: str
) -> List[Dict[str, str]]:
    page = 1
    collected: Dict[str, Dict[str, str]] = {}

    while True:
        params = {
            "pageMode": "explore",
            "page": page,
            "company": company_name,
            "sortBy": "submissions",
        }
        response = session.get(PRACTICE_API_PROBLEMS_URL, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()

        for problem in payload.get("results", []):
            raw_url = (problem.get("problem_url") or "").strip()
            if not raw_url:
                continue

            problem_url = urljoin(PRACTICE_SITE_BASE_URL, raw_url)
            if problem_url not in collected:
                collected[problem_url] = {
                    "company": company_name,
                    "company_explore_url": company_explore_url,
                    "problem_name": (problem.get("problem_name") or "Unknown Problem").strip(),
                    "problem_url": problem_url,
                    "difficulty": (problem.get("difficulty") or "Unknown").strip(),
                    "page": str(page),
                }

        next_page = payload.get("next")
        if not next_page:
            break

        try:
            next_page_number = int(next_page)
        except (TypeError, ValueError):
            break

        if next_page_number <= page:
            break

        page = next_page_number
        time.sleep(REQUEST_DELAY_SECONDS)

    return sorted(collected.values(), key=lambda item: item["problem_name"].lower())


def save_stage2_outputs(stage2_rows: List[Dict[str, str]]) -> None:
    write_json(OUTPUT_DIR / "stage2_all_problem_links.json", stage2_rows)
    write_stage2_csv(OUTPUT_DIR / "stage2_all_problem_links.csv", stage2_rows)

    company_groups: Dict[str, List[Dict[str, str]]] = {}
    for row in stage2_rows:
        company_groups.setdefault(row["company"], []).append(row)

    company_index = []
    for company_name, rows in sorted(company_groups.items(), key=lambda item: item[0].lower()):
        company_dir = OUTPUT_DIR / "stage2_company_wise" / sanitize_name(company_name)
        write_json(company_dir / "problem_links.json", rows)
        write_stage2_csv(company_dir / "problem_links.csv", rows)
        company_index.append(
            {
                "company": company_name,
                "problem_link_count": len(rows),
                "folder": str(company_dir.as_posix()),
            }
        )

    write_json(OUTPUT_DIR / "stage2_companies_index.json", company_index)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_multiline(value: str) -> str:
    lines = [line.strip() for line in (value or "").splitlines()]
    return "\n".join([line for line in lines if line])


def extract_constraints_text(full_text: str) -> str:
    full_text_lower = full_text.lower()
    start_index = full_text_lower.find("constraints")
    if start_index == -1:
        return ""

    snippet = full_text[start_index:]
    return clean_multiline(snippet)


def extract_statement_text(full_text: str) -> str:
    if not full_text:
        return ""
    markers = ["Examples:", "Example:", "Constraints:"]
    cut_positions = [full_text.find(marker) for marker in markers if full_text.find(marker) != -1]
    if not cut_positions:
        return clean_multiline(full_text)
    return clean_multiline(full_text[: min(cut_positions)])


def parse_problem_question_html(problem_html: str) -> Dict[str, object]:
    fragment = BeautifulSoup(problem_html or "", "html.parser")

    for node in fragment.select("#highlighter--hover-tools, #highlighter--hover-tools--container"):
        node.decompose()

    examples = [clean_multiline(pre.get_text("\n", strip=True)) for pre in fragment.find_all("pre")]
    examples = [entry for entry in examples if entry]

    full_text = clean_multiline(fragment.get_text("\n", strip=True))
    constraints_text = extract_constraints_text(full_text)
    statement_text = extract_statement_text(full_text)

    return {
        "statement_text": statement_text,
        "full_text": full_text,
        "examples": examples,
        "constraints_text": constraints_text,
        "question_html": problem_html or "",
    }


def fetch_problem_details(session: requests.Session, problem_url: str) -> Dict[str, object]:
    soup = fetch_soup(session, problem_url)
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag or not next_data_tag.string:
        raise RuntimeError("Could not find __NEXT_DATA__ payload")

    payload = json.loads(next_data_tag.string)
    prob_data = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("problemData", {})
        .get("allData", {})
        .get("probData", {})
    )

    if not prob_data:
        raise RuntimeError("Problem data payload is empty")

    question_blob = parse_problem_question_html(prob_data.get("problem_question") or "")
    tags = prob_data.get("tags") if isinstance(prob_data.get("tags"), dict) else {}

    return {
        "problem_url": problem_url,
        "problem_name": clean_text(prob_data.get("problem_name") or "Unknown Problem"),
        "slug": clean_text(prob_data.get("slug") or ""),
        "difficulty": clean_text(prob_data.get("difficulty") or prob_data.get("problem_level_text") or "Unknown"),
        "accuracy": clean_text(prob_data.get("accuracy") or ""),
        "marks": prob_data.get("marks"),
        "all_submissions": prob_data.get("all_submissions"),
        "problem_type": clean_text(prob_data.get("problem_type_text") or ""),
        "visibility": clean_text(prob_data.get("visibility_text") or ""),
        "input_format": prob_data.get("input_format") if isinstance(prob_data.get("input_format"), dict) else {},
        "tags": tags,
        "topic_tags": tags.get("topic_tags", []) if isinstance(tags, dict) else [],
        "company_tags": tags.get("company_tags", []) if isinstance(tags, dict) else [],
        "article_list": prob_data.get("article_list", []),
        "interview_links": prob_data.get("interview_links", []),
        "statement_text": question_blob["statement_text"],
        "full_text": question_blob["full_text"],
        "examples": question_blob["examples"],
        "constraints_text": question_blob["constraints_text"],
        "question_html": question_blob["question_html"],
    }


def fetch_problem_details_with_retry(problem_url: str) -> Dict[str, object]:
    local_session = make_session()
    return fetch_problem_details(local_session, problem_url)


def load_stage2_rows() -> List[Dict[str, str]]:
    if not STAGE2_LINKS_FILE.exists():
        return []

    with STAGE2_LINKS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def run_stage3(session: requests.Session, stage2_rows: List[Dict[str, str]]) -> None:
    if not stage2_rows:
        print("Stage 3 skipped: no stage2 rows available")
        return

    unique_problem_urls = sorted(
        {
            clean_text(row.get("problem_url", ""))
            for row in stage2_rows
            if clean_text(row.get("problem_url", ""))
        }
    )

    print(f"Stage 3: fetching detailed question data for {len(unique_problem_urls)} unique URLs")

    details_cache: Dict[str, Dict[str, object]] = {}
    fetch_errors: List[Dict[str, str]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=STAGE3_MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_problem_details_with_retry, problem_url): problem_url
            for problem_url in unique_problem_urls
        }
        completed = 0
        for future in concurrent.futures.as_completed(future_to_url):
            problem_url = future_to_url[future]
            completed += 1
            if completed % 25 == 0 or completed == len(unique_problem_urls):
                print(f"[Stage3] Processed {completed}/{len(unique_problem_urls)} URLs")
            try:
                details_cache[problem_url] = future.result()
            except Exception as error:  # pylint: disable=broad-except
                fetch_errors.append({"problem_url": problem_url, "error": str(error)})

    stage3_records: List[Dict[str, object]] = []
    company_buckets: Dict[str, List[Dict[str, object]]] = {}

    for row in stage2_rows:
        company_name = clean_text(row.get("company", "Unknown Company"))
        problem_url = clean_text(row.get("problem_url", ""))
        details = details_cache.get(problem_url)
        if not details:
            continue

        record = {
            "company": company_name,
            "company_explore_url": row.get("company_explore_url", ""),
            "stage2_difficulty": row.get("difficulty", "Unknown"),
            "problem_page": details,
        }
        stage3_records.append(record)
        company_buckets.setdefault(company_name, []).append(record)

    write_json(OUTPUT_DIR / "stage3_all_questions_detailed.json", stage3_records)
    write_json(OUTPUT_DIR / "stage3_unique_questions_detailed.json", list(details_cache.values()))
    write_json(OUTPUT_DIR / "stage3_fetch_errors.json", fetch_errors)

    stage3_company_index = []
    for company_name, records in sorted(company_buckets.items(), key=lambda item: item[0].lower()):
        company_dir = OUTPUT_DIR / "stage3_company_wise" / sanitize_name(company_name)
        write_json(company_dir / "questions_detailed.json", records)
        stage3_company_index.append(
            {
                "company": company_name,
                "question_count": len(records),
                "folder": str(company_dir.as_posix()),
            }
        )

    write_json(OUTPUT_DIR / "stage3_companies_index.json", stage3_company_index)
    print(
        "Stage 3 saved "
        f"{len(stage3_records)} company-question records and {len(details_cache)} unique question pages"
    )
    if fetch_errors:
        print(f"Stage 3 fetch errors: {len(fetch_errors)}")


def save_outputs(all_questions: List[Dict[str, str]]) -> None:
    companies: Dict[str, List[Dict[str, str]]] = {}
    by_difficulty: Dict[str, List[Dict[str, str]]] = {}

    for question in all_questions:
        companies.setdefault(question["company"], []).append(question)
        by_difficulty.setdefault(question["difficulty"], []).append(question)

    write_json(OUTPUT_DIR / "all_questions.json", all_questions)
    write_csv(OUTPUT_DIR / "all_questions.csv", all_questions)

    companies_index = []
    for company_name, questions in sorted(companies.items(), key=lambda item: item[0].lower()):
        company_dir = OUTPUT_DIR / "company_wise" / sanitize_name(company_name)
        write_json(company_dir / "questions.json", questions)
        write_csv(company_dir / "questions.csv", questions)
        companies_index.append(
            {
                "company": company_name,
                "question_count": len(questions),
                "folder": str(company_dir.as_posix()),
            }
        )
    write_json(OUTPUT_DIR / "companies_index.json", companies_index)

    for difficulty, questions in sorted(by_difficulty.items(), key=lambda item: item[0].lower()):
        difficulty_dir = OUTPUT_DIR / "difficulty_wise" / sanitize_name(difficulty)
        write_json(difficulty_dir / "questions.json", questions)
        write_csv(difficulty_dir / "questions.csv", questions)


def main() -> None:
    session = make_session()

    existing_stage2_rows = load_stage2_rows()
    if existing_stage2_rows:
        print(f"Using existing stage2 links file: {STAGE2_LINKS_FILE}")
        run_stage3(session, existing_stage2_rows)
        return

    print(f"Discovering company pages from: {BASE_URL}")
    company_pages = discover_company_links(session)
    print(f"Found {len(company_pages)} company pages")

    stage1_links = [
        {"company": company_name, "url": company_url}
        for company_url, company_name in company_pages
    ]
    write_json(OUTPUT_DIR / "stage1_company_links.json", stage1_links)

    stage2_rows: List[Dict[str, str]] = []
    for index, (company_url, company_name) in enumerate(company_pages, start=1):
        print(f"[Stage2 {index}/{len(company_pages)}] {company_name}")
        try:
            rows = fetch_company_problem_links(session, company_name, company_url)
            stage2_rows.extend(rows)
            print(f"    Collected {len(rows)} problem links")
        except Exception as error:  # pylint: disable=broad-except
            print(f"    Failed: {error}")
        time.sleep(REQUEST_DELAY_SECONDS)

    dedup_stage2: Dict[str, Dict[str, str]] = {}
    for item in stage2_rows:
        dedup_stage2[f"{item['company']}::{item['problem_url']}"] = item

    final_stage2 = sorted(
        dedup_stage2.values(),
        key=lambda item: (item["company"].lower(), item["problem_name"].lower()),
    )
    save_stage2_outputs(final_stage2)
    print(f"Saved Stage 2 problem links: {len(final_stage2)}")

    run_stage3(session, final_stage2)
    return

    all_questions: List[Dict[str, str]] = []
    for index, (company_url, company_name) in enumerate(company_pages, start=1):
        print(f"[{index}/{len(company_pages)}] Crawling {company_name} -> {company_url}")
        try:
            questions = extract_questions_for_company(session, company_name, company_url)
            all_questions.extend(questions)
            print(f"    Collected {len(questions)} questions")
        except Exception as error:  # pylint: disable=broad-except
            print(f"    Failed: {error}")
        time.sleep(REQUEST_DELAY_SECONDS)

    deduped: Dict[str, Dict[str, str]] = {}
    for item in all_questions:
        key = f"{item['company']}::{item['question_url']}"
        deduped[key] = item

    final_questions = sorted(
        deduped.values(),
        key=lambda q: (q["company"].lower(), q["difficulty"].lower(), q["question"].lower()),
    )

    save_outputs(final_questions)
    print(f"Saved {len(final_questions)} questions into {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()

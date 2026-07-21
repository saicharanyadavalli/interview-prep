import requests
from bs4 import BeautifulSoup
import json
import re
import os

BASE_URL = "https://sqlbolt.com"

def get_sidebar_links():
    url = f"{BASE_URL}/lesson/select_queries_introduction"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch initial page: {resp.status_code}")
        return []
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    links = []
    ignored_slugs = {'introduction'}

    for a in soup.find_all('a', href=True):
        href = a['href']
        title = a.get_text().strip()
        if href.startswith('/lesson/') or href.startswith('/topic/'):
            slug = href.rstrip('/').split('/')[-1]
            if slug in ignored_slugs:
                continue
            if href not in [l['href'] for l in links]:
                links.append({'href': href, 'title': title, 'slug': slug})
                
    return links

def parse_lesson(link_info, order_idx):
    url = f"{BASE_URL}{link_info['href']}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch {url}: {resp.status_code}")
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')
    slug = link_info['slug']

    # Prefer nav link title if descriptive (e.g. "SQL Lesson 1: SELECT queries 101")
    nav_title = link_info['title']
    h1 = soup.find('h1')
    page_title = h1.get_text().strip() if h1 else ""
    
    if page_title and page_title.lower() != "exercise" and not page_title.startswith("Lesson"):
        title = page_title
    else:
        title = nav_title

    container = soup.find('div', id='lesson') or soup.find('div', class_='lesson-body') or soup.find('article') or soup.body

    # Extract tasks
    tasks = []
    exercise_section = soup.find('div', id='exercise') or soup.find('div', class_=re.compile(r'exercise', re.I))
    if exercise_section:
        for li in exercise_section.find_all('li'):
            task_text = re.sub(r'\s+', ' ', li.get_text().strip())
            if task_text and task_text not in tasks:
                tasks.append(task_text)

    if not tasks:
        for ol in soup.find_all('ol'):
            prev = ol.find_previous(['h2', 'h3', 'h4', 'p'])
            if prev and ('exercise' in prev.get_text().lower() or 'task' in prev.get_text().lower()):
                for li in ol.find_all('li'):
                    t_text = re.sub(r'\s+', ' ', li.get_text().strip())
                    if t_text and t_text not in tasks:
                        tasks.append(t_text)

    markdown_parts = []
    elements = container.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'pre', 'table', 'blockquote', 'ul', 'ol'], recursive=True)
    
    seen_elements = set()
    for elem in elements:
        if id(elem) in seen_elements:
            continue
            
        if elem.find_parent(id=['exercise', 'sidebar', 'nav']) or 'exercise' in elem.get('class', []):
            continue

        tag = elem.name
        seen_elements.add(id(elem))

        if tag == 'h1':
            markdown_parts.append(f"# {elem.get_text().strip()}\n")
        elif tag == 'h2':
            if 'exercise' in elem.get_text().lower():
                continue
            markdown_parts.append(f"## {elem.get_text().strip()}\n")
        elif tag == 'h3':
            markdown_parts.append(f"### {elem.get_text().strip()}\n")
        elif tag == 'h4':
            markdown_parts.append(f"#### {elem.get_text().strip()}\n")
        elif tag == 'p':
            p_text = elem.get_text().strip()
            if p_text and not p_text.lower().startswith('exercise:'):
                markdown_parts.append(f"{p_text}\n")
        elif tag == 'pre':
            code_text = elem.get_text().strip()
            markdown_parts.append(f"```sql\n{code_text}\n```\n")
        elif tag == 'table':
            rows = elem.find_all('tr')
            if rows:
                table_md = []
                for i, r in enumerate(rows):
                    cols = [c.get_text().strip() for c in r.find_all(['th', 'td'])]
                    if cols:
                        table_md.append("| " + " | ".join(cols) + " |")
                        if i == 0:
                            table_md.append("| " + " | ".join(['---'] * len(cols)) + " |")
                if table_md:
                    markdown_parts.append("\n".join(table_md) + "\n")
        elif tag == 'ul':
            if elem.find_parent(['ul', 'ol', 'table']):
                continue
            items = []
            for li in elem.find_all('li', recursive=False):
                items.append(f"- {li.get_text().strip()}")
            if items:
                markdown_parts.append("\n".join(items) + "\n")

    content_markdown = "\n".join(markdown_parts).strip()
    content_markdown = re.sub(r'\n{3,}', '\n\n', content_markdown)

    return {
        "slug": slug,
        "order": order_idx,
        "title": title,
        "content_markdown": content_markdown,
        "tasks": tasks
    }

def scrape_all():
    links = get_sidebar_links()
    results = []
    for idx, link in enumerate(links, start=1):
        print(f"Scraping [{idx}/{len(links)}]: {link['title']} ({link['slug']})...")
        lesson_data = parse_lesson(link, idx)
        if lesson_data:
            results.append(lesson_data)
            print(f"  -> Title: {lesson_data['title']}, Tasks: {len(lesson_data['tasks'])}")
            
    out_path = os.path.join(os.path.dirname(__file__), "sqlbolt_courses.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(results)} scraped lessons to {out_path}")
    return results

if __name__ == "__main__":
    scrape_all()

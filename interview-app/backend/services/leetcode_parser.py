"""LeetCode problem Markdown parsing and validation service.

Extracts structured problem data (frontmatter, question number, title, slug,
difficulty, topic tags, description, solution approaches, code solutions)
from repository Markdown files.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import yaml

logger = logging.getLogger(__name__)

# Normalization mapping for code solution languages
LANGUAGE_NORMALIZATION: dict[str, str] = {
    "python3": "python",
    "python": "python",
    "py": "python",
    "java": "java",
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "c": "c",
    "c#": "csharp",
    "csharp": "csharp",
    "cs": "csharp",
    "typescript": "typescript",
    "ts": "typescript",
    "javascript": "javascript",
    "js": "javascript",
    "golang": "go",
    "go": "go",
    "rust": "rust",
    "rs": "rust",
    "kotlin": "kotlin",
    "kt": "kotlin",
    "swift": "swift",
    "ruby": "ruby",
    "rb": "ruby",
    "php": "php",
    "scala": "scala",
    "sql": "sql",
    "mysql": "sql",
    "postgresql": "sql",
    "bash": "bash",
    "sh": "bash",
    "shell": "bash",
}


@dataclass
class ParsedApproach:
    """Represents a single solution approach with its analysis."""

    approach_index: int
    title: str
    intuition_md: str = ""
    time_complexity: str = ""
    space_complexity: str = ""
    explanation_md: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "approach_index": self.approach_index,
            "title": self.title,
            "intuition_md": self.intuition_md,
            "time_complexity": self.time_complexity,
            "space_complexity": self.space_complexity,
            "explanation_md": self.explanation_md,
        }


@dataclass
class ParsedProblem:
    """Canonical representation of a parsed LeetCode problem."""

    qnum: int
    title: str
    slug: str
    difficulty: str  # 'Easy', 'Medium', 'Hard'
    topic_tags: list[str] = field(default_factory=list)
    description_md: str = ""
    approaches: list[ParsedApproach] = field(default_factory=list)
    code_solutions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "qnum": self.qnum,
            "title": self.title,
            "slug": self.slug,
            "difficulty": self.difficulty,
            "topic_tags": self.topic_tags,
            "description_md": self.description_md,
            "approaches": [a.to_dict() for a in self.approaches],
            "code_solutions": self.code_solutions,
        }


def normalize_language(lang_raw: str) -> str:
    """Normalize language identifier to standard lowercase key."""
    cleaned = lang_raw.strip().lower()
    cleaned = re.sub(r"[^\w#+]", "", cleaned)
    return LANGUAGE_NORMALIZATION.get(cleaned, cleaned)


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body text from Markdown."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body_text = parts[2]
            try:
                fm_data = yaml.safe_load(fm_text) or {}
                if isinstance(fm_data, dict):
                    return fm_data, body_text
            except Exception as exc:
                logger.debug("Failed to parse YAML frontmatter: %s", exc)
    return {}, content


def extract_qnum_and_title(
    body: str, fm: dict[str, Any], filename_or_path: str
) -> tuple[int, str]:
    """Extract positive integer question number and clean title from markdown body, frontmatter, or path."""
    qnum = 0
    title = ""

    # Strategy 1: Body markdown heading with markdown link:
    # e.g., `# [1. Two Sum](https://leetcode.com/problems/two-sum)`
    # or `# [0001. Two Sum]`
    m = re.search(r"#\s*\[(\d+)\.\s*([^\]]+)\]", body)
    if m:
        try:
            qnum = int(m.group(1))
            title = m.group(2).strip()
        except (ValueError, TypeError):
            pass

    # Strategy 2: Body markdown heading without brackets:
    # e.g., `# 1. Two Sum` or `## 1. Two Sum` or `# Problem 1: Two Sum`
    if qnum <= 0 or not title:
        m = re.search(r"^#+\s*(?:Problem\s*)?(\d+)\s*[\.:]\s*([^\r\n]+)", body, re.MULTILINE)
        if m:
            try:
                if qnum <= 0:
                    qnum = int(m.group(1))
                if not title:
                    title = m.group(2).strip()
            except (ValueError, TypeError):
                pass

    # Strategy 3: Frontmatter fields
    if qnum <= 0:
        for key in ("qnum", "question_id", "id", "number"):
            val = fm.get(key)
            if val is not None:
                try:
                    cand = int(val)
                    if cand > 0:
                        qnum = cand
                        break
                except (ValueError, TypeError):
                    pass

    if not title and fm.get("title"):
        title = str(fm["title"]).strip()

    # Strategy 4: Relative path or filename
    # e.g. "solution/0000-0099/0001.Two Sum/README_EN.md"
    # or "0001 - Two Sum.md"
    # or "0001.Two Sum.md"
    if filename_or_path:
        norm_path = filename_or_path.replace("\\", "/")
        # Match directory pattern like /0001.Two Sum/
        m = re.search(r"(?:^|/)(\d{1,5})\.([^/]+)(?:/|$)", norm_path)
        if m:
            try:
                path_qnum = int(m.group(1))
                path_title = m.group(2).strip()
                if qnum <= 0:
                    qnum = path_qnum
                if not title:
                    title = path_title
            except (ValueError, TypeError):
                pass

        # Match filename pattern like 0001 - Two Sum.md
        if qnum <= 0 or not title:
            m = re.search(r"(?:^|/)(\d{1,5})\s*-\s*([^/\.]+)\.md$", norm_path, re.IGNORECASE)
            if m:
                try:
                    path_qnum = int(m.group(1))
                    path_title = m.group(2).strip()
                    if qnum <= 0:
                        qnum = path_qnum
                    if not title:
                        title = path_title
                except (ValueError, TypeError):
                    pass

    # Clean title
    if title:
        # If title contains markdown link: [Two Sum](url) -> Two Sum
        title = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", title)
        # Strip HTML tags
        title = re.sub(r"<[^>]+>", "", title)
        title = title.strip()

    return qnum, title


def extract_slug(body: str, fm: dict[str, Any], title: str) -> str:
    """Extract or derive URL-friendly slug."""
    # 1. Frontmatter
    if fm.get("slug"):
        slug_raw = str(fm["slug"]).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug_raw.lower()).strip("-")
        if slug:
            return slug

    # 2. LeetCode URL in body
    # e.g. https://leetcode.com/problems/two-sum/
    m = re.search(r"leetcode\.com/problems/([a-z0-9\-]+)", body, re.IGNORECASE)
    if m:
        cand = m.group(1).lower().strip("-")
        if cand:
            return cand

    # 3. Derive from title
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug


def extract_difficulty(body: str, fm: dict[str, Any]) -> str:
    """Extract difficulty, validating and defaulting to 'Easy'."""
    # 1. Frontmatter
    raw_diff = fm.get("difficulty")
    if raw_diff and isinstance(raw_diff, str):
        norm = raw_diff.strip().capitalize()
        if norm in ("Easy", "Medium", "Hard"):
            return norm

    # 2. Body search
    m = re.search(r"(?:Difficulty|Level)\s*:\s*(Easy|Medium|Hard)\b", body, re.IGNORECASE)
    if m:
        return m.group(1).capitalize()

    # 3. Fallback default
    return "Easy"


def extract_topic_tags(body: str, fm: dict[str, Any]) -> list[str]:
    """Extract topic tags from frontmatter or body."""
    tags: list[str] = []
    fm_tags = fm.get("tags") or fm.get("topic_tags")
    if isinstance(fm_tags, list):
        for t in fm_tags:
            if t is not None:
                cleaned = str(t).strip()
                if cleaned and cleaned not in tags:
                    tags.append(cleaned)
    elif isinstance(fm_tags, str):
        for part in fm_tags.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in tags:
                tags.append(cleaned)

    return tags


def extract_description(body: str) -> str:
    """Extract problem description markdown."""
    # 1. Primary: between <!-- description:start --> and <!-- description:end -->
    m = re.search(r"<!--\s*description:start\s*-->(.*?)<!--\s*description:end\s*-->", body, re.DOTALL)
    if m:
        desc = m.group(1).strip()
        if desc:
            return desc

    # 2. Section: ## Description
    desc_match = re.search(
        r"##\s*Description\s*\n+(.*?)(?=##\s*Solutions?|<!--\s*tabs:start\s*-->|<!--\s*solution:start\s*-->|\Z)",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if desc_match:
        desc = desc_match.group(1).strip()
        lines = [line for line in desc.splitlines() if not line.strip().startswith("[中文文档]")]
        desc = "\n".join(lines).strip()
        if desc:
            return desc

    # 3. Fallback: text before ## Solutions
    sol_split = re.split(r"##\s*Solutions?", body, flags=re.IGNORECASE)
    if len(sol_split) > 1:
        prefix = sol_split[0]
        # Remove top heading # [1. Two Sum]...
        clean_prefix = re.sub(r"^#+\s*\[?[^\]\n]+\]?(?:\([^\)]+\))?", "", prefix.strip(), flags=re.MULTILINE)
        lines = [line for line in clean_prefix.splitlines() if not line.strip().startswith("[中文文档]")]
        desc = "\n".join(lines).strip()
        if desc:
            return desc

    return ""


def extract_complexity(text: str) -> tuple[str, str]:
    """Extract time and space complexity strings from approach explanation."""
    time_comp = ""
    space_comp = ""
    tc_m = re.search(r"Time\s+(?:complexity|Complexity).*?(\$O\(.*?\)\$|O\(.*?\))", text, re.IGNORECASE)
    if tc_m:
        time_comp = tc_m.group(1).strip()

    sc_m = re.search(r"Space\s+(?:complexity|Complexity).*?(\$O\(.*?\)\$|O\(.*?\))", text, re.IGNORECASE)
    if sc_m:
        space_comp = sc_m.group(1).strip()

    return time_comp, space_comp


def extract_tabs_code(tabs_content: str, out_solutions: dict[str, str]) -> None:
    """Extract language tabs and code from <!-- tabs:start --> blocks."""
    content = tabs_content.split("<!-- tabs:end -->")[0]
    pattern = re.compile(r"####\s+([^\n\r]+)\s*\n+```([a-zA-Z0-9_+#]*)\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(content):
        lang_header = m.group(1).strip()
        fence_lang = (m.group(2) or "").strip()
        code = m.group(3).rstrip()

        norm_lang = normalize_language(lang_header) or normalize_language(fence_lang)
        if norm_lang and norm_lang not in out_solutions:
            out_solutions[norm_lang] = code


def extract_fenced_code(text: str, out_solutions: dict[str, str]) -> None:
    """Fallback extraction of fenced code blocks with language identifiers."""
    pattern = re.compile(r"```([a-zA-Z0-9_+#]+)\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(text):
        lang_raw = m.group(1).strip()
        code = m.group(2).rstrip()
        norm_lang = normalize_language(lang_raw)
        if norm_lang and norm_lang not in out_solutions:
            out_solutions[norm_lang] = code


def extract_approaches_and_solutions(
    body: str,
) -> tuple[list[ParsedApproach], dict[str, str]]:
    """Extract approaches and code solutions from problem body."""
    approaches: list[ParsedApproach] = []
    code_solutions: dict[str, str] = {}

    sol_section_m = re.search(r"##\s*Solutions?(.*)", body, re.DOTALL | re.IGNORECASE)
    sol_text = sol_section_m.group(1) if sol_section_m else body

    # Split by ### Solution N: or ### Approach N:
    sol_blocks = re.split(r"###\s+(?:Solution|Approach|Method)\s*\d*[:\-]?\s*", sol_text, flags=re.IGNORECASE)

    if len(sol_blocks) > 1:
        for idx, block in enumerate(sol_blocks[1:], start=1):
            block_lines = block.strip().splitlines()
            title = block_lines[0].strip() if block_lines else f"Approach {idx}"

            tabs_split = re.split(r"<!--\s*tabs:start\s*-->", block)
            explanation_part = tabs_split[0]
            if block_lines:
                explanation_part = explanation_part.replace(block_lines[0], "", 1).strip()

            explanation_md = re.sub(r"<!--\s*solution:[^>]+-->", "", explanation_part).strip()
            time_comp, space_comp = extract_complexity(explanation_md)

            intuition_md = ""
            m_intuition = re.search(
                r"(?:####|\*\*|###)?\s*Intuition:?\s*(?:\*\*)?\s*(.*?)(?=\n\n(?:####|\*\*|###)|Time\s+complexity|Space\s+complexity|\Z)",
                explanation_md,
                re.DOTALL | re.IGNORECASE,
            )
            if m_intuition:
                intuition_md = m_intuition.group(1).strip()
            else:
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", explanation_md) if p.strip()]
                if paragraphs:
                    non_comp = [
                        p for p in paragraphs if not re.match(r"^(?:Time|Space)\s+complexity", p, re.IGNORECASE)
                    ]
                    if non_comp:
                        intuition_md = non_comp[0]

            approaches.append(
                ParsedApproach(
                    approach_index=idx,
                    title=title or f"Approach {idx}",
                    intuition_md=intuition_md,
                    time_complexity=time_comp,
                    space_complexity=space_comp,
                    explanation_md=explanation_md,
                )
            )

            if len(tabs_split) > 1:
                extract_tabs_code(tabs_split[1], code_solutions)

    else:
        # Single solution without explicit Solution N header
        tabs_split = re.split(r"<!--\s*tabs:start\s*-->", sol_text)
        if len(tabs_split) > 1:
            explanation_part = tabs_split[0]
            clean_explanation = re.sub(r"<!--[^>]+-->", "", explanation_part).strip()
            time_comp, space_comp = extract_complexity(clean_explanation)

            intuition_md = ""
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_explanation) if p.strip()]
            if paragraphs:
                non_comp = [
                    p for p in paragraphs if not re.match(r"^(?:Time|Space)\s+complexity", p, re.IGNORECASE)
                ]
                if non_comp:
                    intuition_md = non_comp[0]

            approaches.append(
                ParsedApproach(
                    approach_index=1,
                    title="Solution Approach",
                    intuition_md=intuition_md,
                    time_complexity=time_comp,
                    space_complexity=space_comp,
                    explanation_md=clean_explanation,
                )
            )
            extract_tabs_code(tabs_split[1], code_solutions)
        else:
            extract_fenced_code(sol_text, code_solutions)

    return approaches, code_solutions


def validate_problem(parsed: Optional[ParsedProblem]) -> tuple[bool, str]:
    """Validate a ParsedProblem against database schema and business invariants.

    Returns:
        tuple[bool, str]: (is_valid, error_reason)
    """
    if parsed is None:
        return False, "Parsed problem is None"

    if not isinstance(parsed.qnum, int) or parsed.qnum <= 0:
        return False, f"qnum must be a positive integer (> 0), got: {getattr(parsed, 'qnum', None)}"

    if parsed.difficulty not in ("Easy", "Medium", "Hard"):
        return (
            False,
            f"difficulty must be one of ('Easy', 'Medium', 'Hard'), got: '{getattr(parsed, 'difficulty', None)}'",
        )

    if not isinstance(parsed.title, str) or not parsed.title.strip():
        return False, "title must be a non-empty string"

    if not isinstance(parsed.slug, str) or not parsed.slug.strip():
        return False, "slug must be a non-empty string"

    if not isinstance(parsed.description_md, str) or not parsed.description_md.strip():
        return False, "description_md must be a non-empty string"

    return True, ""


def parse_leetcode_markdown(
    content: str, filename_or_path: str = ""
) -> Optional[ParsedProblem]:
    """Parse Markdown content of a LeetCode problem into a ParsedProblem.

    Args:
        content: Raw markdown text of the problem file.
        filename_or_path: Optional relative path or filename (e.g.
            'solution/0000-0099/0001.Two Sum/README_EN.md' or '0001 - Two Sum.md').

    Returns:
        Optional[ParsedProblem]: Structured problem if valid, None if malformed or non-problem file.
    """
    if not content or not content.strip():
        return None

    # 1. Frontmatter
    fm, body = extract_frontmatter(content)

    # 2. Question number and title
    qnum, title = extract_qnum_and_title(body, fm, filename_or_path)
    if qnum <= 0 or not title:
        return None

    # 3. Slug
    slug = extract_slug(body, fm, title)

    # 4. Difficulty
    difficulty = extract_difficulty(body, fm)

    # 5. Topic Tags
    topic_tags = extract_topic_tags(body, fm)

    # 6. Description
    description_md = extract_description(body)

    # 7. Approaches and Code Solutions
    approaches, code_solutions = extract_approaches_and_solutions(body)

    parsed = ParsedProblem(
        qnum=qnum,
        title=title,
        slug=slug,
        difficulty=difficulty,
        topic_tags=topic_tags,
        description_md=description_md,
        approaches=approaches,
        code_solutions=code_solutions,
    )

    is_valid, reason = validate_problem(parsed)
    if not is_valid:
        logger.debug("Validation failed for problem %d: %s", qnum, reason)
        return None

    return parsed

"""Shared constants and helpers for the System Design learning track."""

from __future__ import annotations

from pathlib import Path
import json


SYSTEM_DESIGN_STEP_COUNT = 30
SYSTEM_DESIGN_QNUM_BASE = 900_000


def step_to_qnum(step_no: int) -> int:
    """Map a 1-based step number to a reserved qnum in user_progress."""
    return SYSTEM_DESIGN_QNUM_BASE + int(step_no)


def qnum_to_step(qnum: int) -> int | None:
    """Return 1-based step number when qnum belongs to system design range."""
    value = int(qnum or 0)
    if not is_system_design_qnum(value):
        return None
    return value - SYSTEM_DESIGN_QNUM_BASE


def is_system_design_qnum(qnum: int) -> bool:
    """Whether qnum is reserved for System Design course progress tracking."""
    value = int(qnum or 0)
    return SYSTEM_DESIGN_QNUM_BASE < value <= SYSTEM_DESIGN_QNUM_BASE + SYSTEM_DESIGN_STEP_COUNT


def load_system_design_titles() -> dict[int, str]:
    """Load step titles from the generated frontend course index when available."""
    index_path = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend"
        / "assets"
        / "system-design"
        / "course-index.json"
    )
    if not index_path.exists():
        return {}

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    titles: dict[int, str] = {}
    for step in payload.get("steps", []):
        try:
            step_no = int(step.get("step_no", 0) or 0)
        except Exception:
            continue
        if step_no <= 0:
            continue
        title = str(step.get("title", "")).strip()
        if title:
            titles[step_no] = title
    return titles

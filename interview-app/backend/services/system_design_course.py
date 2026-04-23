"""Shared constants and helpers for learning-track progress mappings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class LearningTrackConfig:
    """Static learning-track settings used across backend routes and services."""

    track_id: str
    display_name: str
    step_count: int
    qnum_base: int
    assets_slug: str


LEARNING_TRACKS: dict[str, LearningTrackConfig] = {
    "system-design": LearningTrackConfig(
        track_id="system-design",
        display_name="System Design",
        step_count=30,
        qnum_base=900_000,
        assets_slug="system-design",
    ),
    "object-oriented-design": LearningTrackConfig(
        track_id="object-oriented-design",
        display_name="Object-Oriented Design",
        step_count=14,
        qnum_base=910_000,
        assets_slug="object-oriented-design",
    ),
    "mobile-system-design": LearningTrackConfig(
        track_id="mobile-system-design",
        display_name="Mobile System Design",
        step_count=11,
        qnum_base=920_000,
        assets_slug="mobile-system-design",
    ),
    "ml-system-design": LearningTrackConfig(
        track_id="ml-system-design",
        display_name="ML System Design",
        step_count=11,
        qnum_base=930_000,
        assets_slug="ml-system-design",
    ),
    "genai-system-design": LearningTrackConfig(
        track_id="genai-system-design",
        display_name="GenAI System Design",
        step_count=11,
        qnum_base=940_000,
        assets_slug="genai-system-design",
    ),
}

SYSTEM_DESIGN_STEP_COUNT = LEARNING_TRACKS["system-design"].step_count
SYSTEM_DESIGN_QNUM_BASE = LEARNING_TRACKS["system-design"].qnum_base


def get_learning_track_config(track_id: str) -> LearningTrackConfig | None:
    """Return learning-track config by id when configured."""
    return LEARNING_TRACKS.get(str(track_id or "").strip())


def get_learning_tracks() -> list[LearningTrackConfig]:
    """Return all learning-track configs in insertion order."""
    return list(LEARNING_TRACKS.values())


def step_to_track_qnum(track_id: str, step_no: int) -> int:
    """Map a 1-based track step number to a reserved qnum in user_progress."""
    config = get_learning_track_config(track_id)
    if not config:
        raise ValueError(f"Unknown learning track: {track_id}")
    return config.qnum_base + int(step_no)


def track_qnum_to_step(track_id: str, qnum: int) -> int | None:
    """Return 1-based step number when qnum belongs to a configured track range."""
    config = get_learning_track_config(track_id)
    if not config:
        return None
    value = int(qnum or 0)
    if not is_track_qnum(track_id, value):
        return None
    return value - config.qnum_base


def is_track_qnum(track_id: str, qnum: int) -> bool:
    """Whether qnum is reserved for a specific learning-track progress range."""
    config = get_learning_track_config(track_id)
    if not config:
        return False
    value = int(qnum or 0)
    return config.qnum_base < value <= config.qnum_base + config.step_count


def is_reserved_learning_track_qnum(qnum: int) -> bool:
    """Whether qnum belongs to any learning-track reserved range."""
    value = int(qnum or 0)
    for config in LEARNING_TRACKS.values():
        if config.qnum_base < value <= config.qnum_base + config.step_count:
            return True
    return False


def step_to_qnum(step_no: int) -> int:
    """Back-compat helper for system design step->qnum mapping."""
    return step_to_track_qnum("system-design", step_no)


def qnum_to_step(qnum: int) -> int | None:
    """Back-compat helper for system design qnum->step mapping."""
    return track_qnum_to_step("system-design", qnum)


def is_system_design_qnum(qnum: int) -> bool:
    """Back-compat helper for system design qnum range checks."""
    return is_track_qnum("system-design", qnum)


def load_learning_track_titles(track_id: str) -> dict[int, str]:
    """Load step titles from generated frontend course index for a track."""
    config = get_learning_track_config(track_id)
    if not config:
        return {}

    index_path = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend"
        / "assets"
        / config.assets_slug
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


def load_system_design_titles() -> dict[int, str]:
    """Back-compat helper for system design titles."""
    return load_learning_track_titles("system-design")

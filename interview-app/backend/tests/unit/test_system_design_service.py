"""Unit tests for system_design_course track configurations and step-to-qnum conversions."""

import pytest
from services.system_design_course import (
    LEARNING_TRACKS,
    get_learning_track_config,
    get_learning_tracks,
    step_to_track_qnum,
    track_qnum_to_step,
    is_track_qnum,
    is_reserved_learning_track_qnum,
)


def test_all_five_learning_tracks_configured():
    """Verify the 5 expected learning tracks are registered."""
    track_ids = {t.track_id for t in get_learning_tracks()}
    assert track_ids == {
        "system-design",
        "object-oriented-design",
        "mobile-system-design",
        "ml-system-design",
        "genai-system-design",
    }


@pytest.mark.parametrize("track_id,step_no,expected_qnum", [
    ("system-design", 1, 900001),
    ("system-design", 30, 900030),
    ("object-oriented-design", 1, 910001),
    ("mobile-system-design", 5, 920005),
    ("ml-system-design", 11, 930011),
    ("genai-system-design", 7, 940007),
])
def test_step_to_track_qnum_and_inverse(track_id: str, step_no: int, expected_qnum: int):
    """Verify mapping of step numbers to qnum base offsets and reverse resolution."""
    calculated_qnum = step_to_track_qnum(track_id, step_no)
    assert calculated_qnum == expected_qnum

    resolved_step = track_qnum_to_step(track_id, calculated_qnum)
    assert resolved_step == step_no
    assert is_track_qnum(track_id, calculated_qnum) is True
    assert is_reserved_learning_track_qnum(calculated_qnum) is True


def test_step_to_track_qnum_invalid_track_raises():
    """Verify ValueError is raised when providing an unknown track ID."""
    with pytest.raises(ValueError):
        step_to_track_qnum("unknown-track", 1)


def test_is_reserved_learning_track_qnum_returns_false_for_standard_dsa_qnum():
    """Verify regular DSA question numbers (e.g. 1 to 5000) are not marked as learning track reserved."""
    assert is_reserved_learning_track_qnum(1) is False
    assert is_reserved_learning_track_qnum(500) is False
    assert is_reserved_learning_track_qnum(899999) is False

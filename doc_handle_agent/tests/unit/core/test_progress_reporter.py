"""Unit tests for ProgressReporter."""

import pytest

from app.core.progress_reporter import ProgressReporter
from app.core.state import create_initial_state


@pytest.mark.asyncio
async def test_report_step_maps_to_global_progress() -> None:
    """Step-based progress should map correctly to global progress."""
    state = create_initial_state(repo_id="r1", template_id="t1")
    reporter = ProgressReporter(
        state=state,
        node_name="node_a",
        node_weight=0.5,
        completed_weight=0.2,
    )

    await reporter.report_step(current=2, total=4, message="halfway")

    assert state["progress"] == 45.0  # 0.2 + 0.5 * 0.5 = 0.45 -> 45.0
    assert state["message"] == "halfway"


@pytest.mark.asyncio
async def test_report_percent_maps_to_global_progress() -> None:
    """Percent-based progress should map correctly to global progress."""
    state = create_initial_state(repo_id="r1", template_id="t1")
    reporter = ProgressReporter(
        state=state,
        node_name="node_b",
        node_weight=0.4,
        completed_weight=0.3,
    )

    await reporter.report_percent(percent=50.0, message="mid")

    assert state["progress"] == 50.0  # 0.3 + 0.4 * 0.5 = 0.5 -> 50.0
    assert state["message"] == "mid"


@pytest.mark.asyncio
async def test_progress_clamped_to_100() -> None:
    """Progress should never exceed 100 even if math goes over."""
    state = create_initial_state(repo_id="r1", template_id="t1")
    reporter = ProgressReporter(
        state=state,
        node_name="node_c",
        node_weight=0.6,
        completed_weight=0.5,
    )

    await reporter.report_percent(percent=100.0)

    # 0.5 + 0.6 * 1.0 = 1.1 -> clamped to 100.0
    assert state["progress"] == 100.0


@pytest.mark.asyncio
async def test_progress_does_not_decrease_message_when_none() -> None:
    """Calling report with message=None should not overwrite existing message."""
    state = create_initial_state(repo_id="r1", template_id="t1")
    state["message"] = "existing"
    reporter = ProgressReporter(
        state=state,
        node_name="node_d",
        node_weight=0.2,
        completed_weight=0.1,
    )

    await reporter.report_step(current=1, total=2, message=None)

    assert state["message"] == "existing"

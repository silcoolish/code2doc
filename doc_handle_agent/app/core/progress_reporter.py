"""Progress reporter for hierarchical progress tracking."""

import asyncio
import logging

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ProgressReporter:
    """Reports progress within a node and maps it to global progress."""

    def __init__(
        self,
        state: dict,
        node_name: str,
        node_weight: float,
        completed_weight: float,
    ) -> None:
        """Initialize the reporter.

        Args:
            state: Agent state dictionary.
            node_name: Name of the current node.
            node_weight: Share of global progress for this node (0-1).
            completed_weight: Sum of all previous nodes' weights.
        """
        self.state = state
        self.node_name = node_name
        self.node_weight = node_weight
        self.completed_weight = completed_weight
        self._lock = asyncio.Lock()

    async def report_step(self, current: int, total: int, message: str | None = None) -> None:
        """Report progress based on step counts.

        Args:
            current: Current step number.
            total: Total number of steps.
            message: Optional status message.
        """
        if total <= 0:
            progress = self.completed_weight
        else:
            progress = self.completed_weight + self.node_weight * (current / total)
        await self._update_state(progress, message)

    async def report_percent(self, percent: float, message: str | None = None) -> None:
        """Report progress based on a percentage.

        Args:
            percent: Internal percentage (0-100).
            message: Optional status message.
        """
        progress = self.completed_weight + self.node_weight * (percent / 100.0)
        await self._update_state(progress, message)

    async def _update_state(self, progress: float, message: str | None = None) -> None:
        """Update the shared state with the calculated progress.

        Args:
            progress: Calculated global progress value.
            message: Optional status message.
        """
        try:
            async with self._lock:
                self.state["progress"] = min(100.0, max(0.0, round(progress * 100, 2)))
                if message is not None:
                    self.state["message"] = message
        except Exception:
            logger.warning("Failed to update progress state", exc_info=True)

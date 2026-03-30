"""Abstract base class for all pipeline stations."""

from __future__ import annotations

import abc
import asyncio
import time

from conveyor_belt.config import ConveyorBeltConfig
from conveyor_belt.context import StationContext
from conveyor_belt.models import StationResult


class Station(abc.ABC):
    """A single validation station on the conveyor belt."""

    name: str = "base"

    def __init__(self, config: ConveyorBeltConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def run(self, ctx: StationContext) -> StationResult:
        """Execute the station's validation logic."""

    async def execute(self, ctx: StationContext, timeout: float = 300.0) -> StationResult:
        """Wrapper that adds timing and a timeout to every station run."""
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.run(ctx), timeout=timeout)
        except asyncio.TimeoutError:
            result = StationResult(
                station_name=self.name,
                passed=False,
                summary=f"Station timed out after {timeout}s",
            )
        result.duration_seconds = round(time.perf_counter() - start, 3)
        return result

from __future__ import annotations
import asyncio
import logging
import math
from collections.abc import Callable, Coroutine
from typing import Any, TypeAlias
from attrs import define, field

LOGGER = logging.getLogger("PySeq")

AsyncFn: TypeAlias = Callable[[], Coroutine[Any, Any, float]]


@define
class _Channel:
    name: str
    fn: AsyncFn
    interval: float
    _task: asyncio.Task | None = field(init=False, default=None)
    _stop_event: asyncio.Event = field(init=False, factory=asyncio.Event)


@define
class Monitor:
    """Background monitor that polls named async callables at independent intervals.

    Each channel runs its own asyncio.Task. Results are written to the log;
    healthy[name] tracks whether the last poll succeeded.

    Usage:
        monitor = Monitor()
        monitor.register("FlowCellA_temperature", fc_a.TemperatureController.get_temperature, interval=30)
        monitor.register("Laser_green_power", laser.get_power, interval=10)
        monitor.start()
    """

    healthy: dict[str, bool] = field(factory=dict)
    _channels: dict[str, _Channel] = field(factory=dict)

    def register(self, name: str, fn: AsyncFn, interval: float) -> None:
        """Register a channel. Safe to call before or after start()."""
        ch = _Channel(name=name, fn=fn, interval=interval)
        self._channels[name] = ch
        self.healthy[name] = False
        if self._running:
            self._start_channel(ch)

    @property
    def _running(self) -> bool:
        return any(
            ch._task is not None and not ch._task.done()
            for ch in self._channels.values()
        )

    def start(self) -> None:
        """Start polling all registered channels. Idempotent."""
        for ch in self._channels.values():
            self._start_channel(ch)

    def _start_channel(self, ch: _Channel) -> None:
        if ch._task is not None and not ch._task.done():
            return
        ch._stop_event.clear()
        ch._task = asyncio.create_task(self._poll_loop(ch), name=f"Monitor:{ch.name}")
        LOGGER.info(f"Monitor :: {ch.name} started (interval={ch.interval}s)")

    def stop(self) -> None:
        """Signal all channels to stop after their current poll."""
        for ch in self._channels.values():
            ch._stop_event.set()

    async def stop_and_wait(self, timeout: float = 5.0) -> None:
        """Stop all channels and await completion."""
        self.stop()
        tasks = [ch._task for ch in self._channels.values() if ch._task is not None]
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=timeout
                )
            except asyncio.TimeoutError:
                pass

    async def _poll_once(self, ch: _Channel) -> None:
        try:
            value = await ch.fn()
            if math.isnan(value):
                raise ValueError(f"{ch.name} returned NaN")
            self.healthy[ch.name] = True
            LOGGER.info(f"Monitor :: {ch.name} = {value}")
        except Exception as exc:
            self.healthy[ch.name] = False
            LOGGER.warning(f"Monitor :: {ch.name} poll failed: {exc}")

    async def _poll_loop(self, ch: _Channel) -> None:
        while not ch._stop_event.is_set():
            await self._poll_once(ch)
            # asyncio.shield prevents the inner wait() from being cancelled
            # when wait_for times out, letting stop() wake this loop immediately.
            try:
                await asyncio.wait_for(
                    asyncio.shield(ch._stop_event.wait()), timeout=ch.interval
                )
            except asyncio.TimeoutError:
                pass
        LOGGER.info(f"Monitor :: {ch.name} stopped")

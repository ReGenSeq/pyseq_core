import asyncio
import pytest
from pyseq_core.monitor import Monitor


class MockFn:
    def __init__(self, value: float = 25.0, raises: bool = False):
        self.value = value
        self.raises = raises
        self.call_count = 0

    async def __call__(self) -> float:
        self.call_count += 1
        if self.raises:
            raise RuntimeError("hardware timeout")
        return self.value


@pytest.mark.asyncio
async def test_register_initializes_healthy_false():
    monitor = Monitor()
    monitor.register("chan", MockFn(), interval=30.0)
    assert monitor.healthy["chan"] is False


@pytest.mark.asyncio
async def test_poll_once_happy_path():
    monitor = Monitor()
    fn = MockFn(value=37.0)
    monitor.register("chan", fn, interval=30.0)
    ch = monitor._channels["chan"]
    await monitor._poll_once(ch)
    assert monitor.healthy["chan"] is True
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_poll_once_exception_sets_unhealthy():
    monitor = Monitor()
    fn = MockFn(raises=True)
    monitor.register("chan", fn, interval=30.0)
    ch = monitor._channels["chan"]
    await monitor._poll_once(ch)  # must not raise
    assert monitor.healthy["chan"] is False


@pytest.mark.asyncio
async def test_poll_once_nan_return_sets_unhealthy():
    monitor = Monitor()
    fn = MockFn(value=float("nan"))
    monitor.register("chan", fn, interval=30.0)
    ch = monitor._channels["chan"]
    await monitor._poll_once(ch)
    assert monitor.healthy["chan"] is False


@pytest.mark.asyncio
async def test_multiple_channels_independent():
    monitor = Monitor()
    good = MockFn(value=25.0)
    bad = MockFn(raises=True)
    monitor.register("good", good, interval=30.0)
    monitor.register("bad", bad, interval=30.0)
    for ch in monitor._channels.values():
        await monitor._poll_once(ch)
    assert monitor.healthy["good"] is True
    assert monitor.healthy["bad"] is False


@pytest.mark.asyncio
async def test_start_stop_and_wait():
    monitor = Monitor()
    monitor.register("chan", MockFn(), interval=60.0)
    monitor.start()
    assert monitor._running
    await monitor.stop_and_wait(timeout=2.0)
    assert not monitor._running


@pytest.mark.asyncio
async def test_start_idempotent():
    monitor = Monitor()
    monitor.register("chan", MockFn(), interval=60.0)
    monitor.start()
    task_id = id(monitor._channels["chan"]._task)
    monitor.start()
    assert id(monitor._channels["chan"]._task) == task_id
    await monitor.stop_and_wait(timeout=2.0)


@pytest.mark.asyncio
async def test_stop_wakes_immediately():
    monitor = Monitor()
    monitor.register("chan", MockFn(), interval=60.0)
    monitor.start()
    await monitor.stop_and_wait(timeout=1.0)
    assert not monitor._running


@pytest.mark.asyncio
async def test_poll_loop_calls_fn():
    monitor = Monitor()
    fn = MockFn(value=25.0)
    monitor.register("chan", fn, interval=0.05)
    monitor.start()
    await asyncio.sleep(0.25)
    await monitor.stop_and_wait(timeout=1.0)
    assert fn.call_count > 1


@pytest.mark.asyncio
async def test_register_after_start():
    monitor = Monitor()
    monitor.register("first", MockFn(), interval=60.0)
    monitor.start()
    assert monitor._running

    fn2 = MockFn(value=10.0)
    monitor.register("second", fn2, interval=0.05)
    await asyncio.sleep(0.15)
    assert monitor._channels["second"]._task is not None
    assert fn2.call_count > 0

    await monitor.stop_and_wait(timeout=2.0)


@pytest.mark.asyncio
async def test_independent_intervals():
    monitor = Monitor()
    slow = MockFn(value=1.0)
    fast = MockFn(value=2.0)
    monitor.register("slow", slow, interval=0.2)
    monitor.register("fast", fast, interval=0.05)
    monitor.start()
    await asyncio.sleep(0.35)
    await monitor.stop_and_wait(timeout=1.0)
    assert fast.call_count > slow.call_count

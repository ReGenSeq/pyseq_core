import pytest
import asyncio
import logging


async def wait_for_microscope_queue(microscope):
    while len(microscope._queue_dict) == 0:
        await asyncio.sleep(0.05)
    assert len(microscope._queue_dict) > 0, "No tasks added to microscope queue"
    microscope.start()
    await microscope._queue.join()


def check_task_sequence(caplog, tasks):
    task_ind = 0
    n_tasks = len(tasks)
    for record in caplog.get_records("call"):
        if tasks[task_ind] in record.msg:
            task_ind += 1
        if task_ind == n_tasks:
            break
    assert task_ind == n_tasks, "Tasks not completed in correct sequence"


def check_for_errors_in_log(caplog):
    errors = []
    for record in caplog.get_records("call"):
        if record.levelno >= logging.ERROR:
            print(record)
            errors.append(record)
    assert len(errors) == 0, "Errors in log"


async def check_fc_queue(
    sequencer, caplog, only_check_filled=False, timeout=None, check_microscope=False
):
    """Check to see if queue gets filled and then emptied."""
    flowcells = [
        fc for fc in sequencer._get_systems_list(None) if fc._pause_event.is_set()
    ]

    try:
        # Check tasks added to queue
        for fc in flowcells:
            assert len(fc._queue_dict) >= 1, f"No tasks added to {fc.name} queue"

        if only_check_filled:
            check_for_errors_in_log(caplog)
            return True

        # Wait for tasks to finish
        _ = []
        for fc in flowcells:
            _.append(fc._queue.join())
        if check_microscope:
            m = sequencer.microscope
            _.append(wait_for_microscope_queue(m))
        try:
            await asyncio.wait_for(asyncio.gather(*_), timeout)
        except TimeoutError as e:
            print(e)
            for fc in flowcells:
                print(fc.name, fc._current_task)

        # Check tasks cleared
        for fc in flowcells:
            assert len(fc._queue_dict) == 0, f"Tasks not cleared from {fc.name} queue"
        if check_microscope:
            assert len(m._queue_dict) == 0, f"Tasks not cleared from {m.name} queue"

        check_for_errors_in_log(caplog)

        return True

    except AssertionError as e:
        print(e)
        return False


@pytest.mark.asyncio
async def test_temperature(BaseTestSequencer):
    for T, timeout in zip([25, 37, 50], [0, None, 1]):
        BaseTestSequencer.temperature(temperature=T, timeout=timeout)


@pytest.mark.asyncio
async def test_pump(BaseTestSequencer, caplog):
    # Positive control
    BaseTestSequencer.pump(volume=100, flow_rate=4000, reagent=1)
    assert await check_fc_queue(BaseTestSequencer, caplog, timeout=1)

    # Negative controls
    neg_cntrls = [
        {"volume": 100, "flow_rate": 4000, "reagent": 25},  # invalid reagent
        {"volume": 1, "flow_rate": 4000, "reagent": 1},  # volume too low
        {"volume": 100, "flow_rate": 12000, "reagent": 1},  # flow rate too hight
    ]
    for params in neg_cntrls:
        try:
            BaseTestSequencer.pump(**params)
            assert False
        except ValueError:
            assert True


@pytest.mark.asyncio
async def test_hold(BaseTestSequencer, caplog):
    BaseTestSequencer.hold(duration=0.01)
    assert await check_fc_queue(BaseTestSequencer, caplog, timeout=1)


@pytest.mark.asyncio
async def test_pause(BaseTestSequencer, caplog):
    # Pause systems and queue hold
    BaseTestSequencer.pause()
    await asyncio.sleep(0.01)
    BaseTestSequencer.hold(duration=0.01 / 60)  # duration in minutes
    # Wait then check to see hold task is still queued
    await asyncio.sleep(0.01)
    assert await check_fc_queue(BaseTestSequencer, caplog, only_check_filled=True)
    # Start queue and check queue completes
    BaseTestSequencer.start()
    assert await check_fc_queue(BaseTestSequencer, caplog, timeout=10)


@pytest.mark.asyncio
async def test_wait(BaseTestSequencerROIs, caplog):
    # Pause systems and queue wait
    BaseTestSequencerROIs.pause()
    BaseTestSequencerROIs.wait()
    # Queue hold on A then image on A and B
    BaseTestSequencerROIs.hold(flowcells="A", duration=0.01 / 60)
    BaseTestSequencerROIs.image()
    # Check tasks queued
    assert await check_fc_queue(
        BaseTestSequencerROIs, caplog, timeout=5, only_check_filled=True
    )
    # Start flowcells and check tasks completed, microscope will start in `check_fc_queue`
    BaseTestSequencerROIs.start("flowcells")
    assert await check_fc_queue(
        BaseTestSequencerROIs, caplog, timeout=5, check_microscope=True
    )
    # Check logs for correct sequence of events
    tasks = ["A using microscope", "B using microscope"]
    check_task_sequence(caplog, tasks)


@pytest.mark.asyncio
async def test_image(BaseTestSequencerROIs, caplog):
    BaseTestSequencerROIs.pause("microscope")
    BaseTestSequencerROIs.image()
    # microscope will start in `check_fc_queue`
    assert await check_fc_queue(
        BaseTestSequencerROIs, caplog, timeout=5, check_microscope=True
    )


@pytest.mark.asyncio
async def test_focus(BaseTestSequencerROIs, caplog):
    BaseTestSequencerROIs.pause("microscope")
    BaseTestSequencerROIs.focus()
    # microscope will start in `check_fc_queue`
    assert await check_fc_queue(
        BaseTestSequencerROIs, caplog, timeout=5, check_microscope=True
    )


@pytest.mark.asyncio
async def test_expose(BaseTestSequencerROIs, caplog):
    BaseTestSequencerROIs.pause("microscope")
    BaseTestSequencerROIs.expose()
    # microscope will start in `check_fc_queue`
    assert await check_fc_queue(
        BaseTestSequencerROIs, caplog, timeout=5, check_microscope=True
    )


@pytest.mark.parametrize(
    "fc, fc_exp",
    [
        ("a", ["A"]),
        ("ab", ["A", "B"]),
        ("flowcell", ["A", "B"]),
        (["b", "a"], ["B", "A"]),
    ],
)
def test_get_fc_list(BaseTestSequencer, fc, fc_exp):
    fcs = BaseTestSequencer._get_systems_list(fc)
    fc_ = [_.name for _ in fcs]
    assert fc_ == fc_exp
    BaseTestSequencer.start()


def test_get_systems_list(BaseTestSequencer):
    fcs = BaseTestSequencer._get_systems_list()
    fc_ = [_.name for _ in fcs]
    assert fc_ == ["A", "B", "microscope"]

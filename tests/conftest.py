import pytest_asyncio
import pytest
import importlib


# Base Test Sequencer
@pytest_asyncio.fixture
async def BaseTestSequencer():
    """Uninitialized Base Test Sequencer with only default settings."""
    # Sequencer Setup
    from sequencers import test_sequencer

    seq = test_sequencer.TestSequencer(name="Test")
    systems = seq._get_systems_list()

    systems.append(seq)
    seq.start()
    seq.initialize()

    await seq._queue.join()

    # Sequencer call
    yield seq

    # Shutdown systems and cancel task workers
    # seq.shutdown()


@pytest.fixture
def test_roi_file_path():
    """Path to test_roi.toml in resources.

    Lists the following ROIs and specifies 1 z plane to image
    flowcell A: roi1A, roi2, roi3
    flowcell B: roi1B, roi2, roie

    """
    resource_path = importlib.resources.files("pyseq_core") / "resources"
    return resource_path / "test_roi.toml"


@pytest.fixture
def BaseTestSequencerROIs(BaseTestSequencer, test_roi_file_path):
    """Base Test sequencer loaded with ROIs from test_roi.toml."""
    BaseTestSequencer.add_rois(["A", "B"], test_roi_file_path)
    return BaseTestSequencer

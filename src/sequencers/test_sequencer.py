from pyseq_core.base_system import (
    BaseFlowCell,
    BaseMicroscope,
    BaseSequencer,
    ROIFactory,
)
from pyseq_core.base_protocol import BaseOpticsParams
from pyseq_core.utils import map_coms

# from pyseq_core.baseROI import BaseROI, TestROI
from pyseq_core.base_instruments import (
    BaseCamera,
    BaseShutter,
    BaseFilter,
    BaseLaser,
    BaseStage,
    BasePump,
    BaseValve,
    BaseTemperatureController,
)
from pyseq_core.utils import DEFAULT_CONFIG
from pyseq_core.base_com import BaseCOM
from typing import Literal, Type, Union
from attrs import define, field
import logging
import asyncio


LOGGER = logging.getLogger("PySeq")

ROI = ROIFactory.factory(DEFAULT_CONFIG)
ROIType = Type[ROI]


@define
class TestCOM(BaseCOM):
    # open: bool = field(default=False)
    __test__ = False  # Add attribute so pytest doesn't try to collect it

    async def connect(self):
        async with self.lock:
            if not self._connected:
                LOGGER.debug(f"connecting to {self.address}")
                self._connected = True
                return f"connected to {self.address}"
            return f"{self.address} shared with another instrument"
        return None

    async def command(self, command: str):
        """Send a command to the instrument."""
        async with self.lock:
            LOGGER.debug(f"{self.name}: Tx: {command}")

    async def close(self):
        async with self.lock:
            LOGGER.debug(f"Closing connection to {self.address}")
            self._connected = False
            return True


class DumbBaseMethods:
    """Concrete methods for: initialize, shutdown, status, and configure.

    Mixin other instrument base classes for testing purposings.
    Need __init__ function for testing.

    Do not use for real concrete instrument classes.
    Do not use __init__ for real instrument classes.

    """

    def __init__(self, name: str, com: TestCOM = None, **kwargs):
        self.name = name
        self.com = com
        self._connected = False

    async def initialize(self):
        """Initialize the instrument."""
        LOGGER.info(f"Initializing {self.name}")

    async def shutdown(self):
        """Shutdown the instrument."""
        LOGGER.info(f"Shutting down {self.name}")

    async def status(self) -> bool:
        """Retrieve the current status of the instrument."""
        return True

    async def configure(self):
        LOGGER.info(f"Configuring {self.name}")

    # async def command(self, command: str):
    #     """Send a command to the instrument."""
    #     # async with self.lock:
    #         # LOGGER.info(f"{self.name}: Tx: {command}")
    #     LOGGER.info(f"{self.name}: Tx: {command}")


COMS_DICT = map_coms(TestCOM)


class TestCamera(DumbBaseMethods, BaseCamera):
    def __init__(self, name: str):
        super().__init__(name=name)
        self._exposure = 1

    async def capture(self):
        """Capture an image."""
        LOGGER.debug(f"Capturing image with {self.name}")
        return True

    async def save_image(self, im_name: str):
        """Save an image"""
        LOGGER.debug(f"{self.name}: Saving image as {im_name}.tif")
        return True

    async def set_exposure(self, time):
        LOGGER.debug(f"{self.name}: Set exposure to {time}")
        self._exposure = time

    async def get_exposure(self):
        return self.exposure


class TestShutter(DumbBaseMethods, BaseShutter):
    def __init__(
        self,
        com: TestCOM,
        name="Shutter",
    ):
        super().__init__(name, com=com)

    async def open(self):
        """Close the shutter."""
        LOGGER.debug(f"Opening shutter {self.name}")
        self._open = True
        return True

    async def close(self):
        """Close the shutter."""
        LOGGER.debug(f"Closing shutter {self.name}")
        self._open = False
        return True


class TestFilterWheel(DumbBaseMethods, BaseFilter):
    def __init__(self, color: str, com: TestCOM):
        super().__init__(f"{color}FilterWheel", com=com)

    async def set_filter(self, filter):
        """Select a filter on the wheel."""
        LOGGER.debug(f"Selecting filter {filter} on {self.name}")
        self._filter = filter

    async def get_filter(self):
        """Select a filter on the wheel."""
        LOGGER.debug(f"Gelecting filter {filter} on {self.name}")
        return self._filter


class TestLaser(DumbBaseMethods, BaseLaser):
    def __init__(self, color: str, com: TestCOM):
        super().__init__(f"{color}Laser", color=color, com=com)
        self._power = 0
        self.color = color

    async def set_power(self, power):
        """Set laser power."""
        LOGGER.debug(f"Setting {self.name} to {power}")
        self._power = power

    async def get_power(self, power):
        """Set laser power."""
        return self.power


class TestYStage(DumbBaseMethods, BaseStage):
    def __init__(
        self,
        com: TestCOM,
        name="YStage",
    ):
        super().__init__(name, com=com)
        self._position = 0

    async def move(self, position):
        LOGGER.debug(f"Moving {self.name} to {position}")
        self.position = position

    async def get_position(self):
        return self._position


class TestXStage(DumbBaseMethods, BaseStage):
    def __init__(self, com: TestCOM, name="XStage"):
        super().__init__(name, com=com)
        self._position = 0

    async def move(self, position):
        LOGGER.debug(f"Moving {self.name} to {position}")
        self.position = position

    async def get_position(self):
        return self._position


class TestTiltStage(DumbBaseMethods, BaseStage):
    def __init__(self, com: TestCOM, name="TiltStage"):
        super().__init__(name, com=com)
        self._position = 0

    async def move(self, position):
        LOGGER.debug(f"Moving {self.name} to {position}")
        self.position = position

    async def get_position(self):
        return self._position


class TestObjectiveStage(DumbBaseMethods, BaseStage):
    def __init__(self, com: TestCOM, name="ZStage"):
        super().__init__(name, com=com)
        self._position = 0

    async def move(self, position):
        LOGGER.debug(f"Moving {self.name} to {position}")
        self.position = position

    async def get_position(self):
        return self._position


class TestPump(DumbBaseMethods, BasePump):
    def __init__(self, name: str, com: TestCOM):
        super().__init__(name, com=com)

    async def pump(self, volume, flow_rate, pause_time=0.1, waste_flow_rate=12000):
        """Pump a specified volume at a specified flow rate."""
        LOGGER.debug(f"{self.name}::Pump {volume} uL at {flow_rate} uL/min")
        LOGGER.debug(f"{self.name}::Pause for {pause_time} s")
        LOGGER.debug(f"{self.name}::Purge at {waste_flow_rate} ul/min")
        return True

    async def reverse_pump(
        self, volume, flow_rate, pause_time=0.1, waste_flow_rate=12000
    ):
        """Pump a specified volume at a specified flow rate."""
        LOGGER.debug(f"{self.name}::Reverse pump {volume} uL at {flow_rate} uL/min")
        LOGGER.debug(f"{self.name}::Pause for {pause_time} s")
        LOGGER.debug(f"{self.name}::Reverse purge at {waste_flow_rate} ul/min")
        return True


@define
class TestValve(DumbBaseMethods, BaseValve):
    def __init__(self, name: str, com: TestCOM):
        super().__init__(name, com=com)

    async def select(self, port):
        """Pump a specified volume at a specified flow rate."""
        LOGGER.debug(f"{self.name}:: Selecting {port}")
        self.port = port
        return True

    async def current_port(self):
        """Read current port from valve."""
        if self._port is None:
            self._port = 1
        return self._port


class TestTemperatureController(DumbBaseMethods, BaseTemperatureController):
    def __init__(self, name: str, com: TestCOM):
        super().__init__(name, com=com)
        self._temperature = 25

    async def set_temperature(self, temperature: float, timeout: Union[None, float]):
        """Set the temperature."""
        LOGGER.debug(f"Setting {self.name} to {temperature}C")
        self._temperature = temperature
        if timeout is None or timeout > 0:
            await asyncio.wait_for(self.wait_for_temperature(temperature), timeout)

    async def get_temperature(self):
        """Get the current temperature."""
        return self._temperature


@define
class TestMicroscope(BaseMicroscope):
    instruments: dict = field(init=False)

    @instruments.default
    def set_instruments(self):
        instruments = {
            "Camera": {
                "Camera_558_687": TestCamera("Camera_558_687"),
                "Camera_610_740": TestCamera("Camera_610_740"),
            },
            "FilterWheel": {
                "red": TestFilterWheel("red", com=COMS_DICT["redFilterWheel"]),
                "green": TestFilterWheel("green", com=COMS_DICT["greenFilterWheel"]),
            },
            "Laser": {
                "red": TestLaser("red", com=COMS_DICT["redLaser"]),
                "green": TestLaser("green", com=COMS_DICT["greenLaser"]),
            },
            "Shutter": TestShutter(com=COMS_DICT["Shutter"]),
            "XStage": TestXStage(com=COMS_DICT["XStage"]),
            "YStage": TestYStage(com=COMS_DICT["YStage"]),
            "TiltStage": TestTiltStage(com=COMS_DICT["TiltStage"]),
            "ZStage": TestObjectiveStage(com=COMS_DICT["ZStage"]),
        }
        return instruments

    async def _configure(self, exp_config):
        LOGGER.debug(f"Configure {self.name}")

    async def _capture(self, roi: ROIType, im_name: str):
        """Capture an image and save it to the specified filename."""

        LOGGER.debug(f"Acquire {im_name}")
        print(self.Shutter.open)
        await self.Shutter.open()
        await self.YStage.move(roi.stage.y_last)
        await self.Shutter.close()
        _ = []
        for c in self.Camera.values():
            _.append(c.save_image(im_name))
        _.append(self.YStage.move(roi.stage.y_init))
        await asyncio.gather(*_)

    async def _z_stack(self, roi: ROIType, im_name: str):
        """Perform a z-stack acquisition."""

        direction = roi.stage.z_direction
        step = roi.stage.z_step
        if direction == 1:
            z_init = roi.stage.z_init
            z_last = roi.stage.z_last
        else:
            z_init = roi.stage.z_last
            z_last = roi.stage.z_init
        LOGGER.debug(f"Z stack {roi.name} {z_init} to {z_last} in {step} steps")
        for i, z in enumerate(range(z_init, z_last, direction * step)):
            LOGGER.debug(f"Z stack {i}/{roi.stage.nz}")
            await self.ZStage.move(z)
            await self._capture(roi, f"{im_name}_z{z}")

    async def _scan(self, roi: ROIType, im_name: str = ""):
        """Perform a scan over the specified region of interest (ROI)."""

        x_init = roi.stage.x_init
        x_last = roi.stage.x_last
        x_step = roi.stage.x_step * roi.stage.x_direction
        LOGGER.debug(
            f"Scanning {roi.name}: XStage: {x_init} to {x_last} in {x_step} increments"
        )
        if len(im_name) == 0:
            im_name = roi.name
        for i, x in enumerate(range(x_init, x_last, x_step)):
            LOGGER.debug(f"XStage {i}/{roi.stage.nx}")
            await self.XStage.move(x)
            await self._z_stack(roi, f"{im_name}_x{x}")

    async def _expose_scan(self, roi: ROIType):
        """Async expose the sample for a specified duration without imaging."""

        x_init = roi.stage.x_init
        x_last = roi.stage.x_last
        x_step = roi.stage.x_step * roi.stage.x_direction
        n_exposures = roi.expose.n_exposures
        LOGGER.debug(
            f"Exposing {roi.name}: XStage: {x_init} to {x_last} in {x_step} increments"
        )
        for i, x in enumerate(range(x_init, x_last, x_step)):
            LOGGER.debug(f"XStage {i}/{roi.stage.nx}")
            await self.XStage.move(x)
            for n in range(n_exposures):
                LOGGER.debug(f"Exposure {n}/{n_exposures}")
                if self.YStage.position == roi.y_init:
                    await self.YStage.move(roi.y_last)
                else:
                    await self.YStage.move(roi.y_init)

    async def _find_focus(self, roi):
        LOGGER.debug(f"Fake finding focus using routine {roi.focus.routine}.")
        LOGGER.debug(f"Saving focus data to {roi.focus.output}.")
        roi.focus.z_focus = 0

    async def _move(self, roi: ROIType):
        """Move the stage ROI x,y,z coordinates."""
        LOGGER.debug(f"Moving to x={roi.x}, y={roi.y}, z={roi.z}")
        await asyncio.gather(
            self.XStage.move(roi.x),
            self.YStage.move(roi.y),
            self.ZStage.move(roi.z),
        )

    async def _set_parameters(
        self, params: BaseOpticsParams, mode: Literal["image", "focus", "expose"]
    ):
        """Set the parameters to expose/image the ROI."""

        params = params.model_dump()[mode]["optics"]
        _ = []
        for color in ["red", "green"]:
            _.append(self.Laser[color].set_power(params["power"][color]))
            _.append(self.FilterWheel[color].set_filter(params["filter"][color]))

        if mode in ["image", "focus"]:
            for c in self.Camera:
                _.append(self.Camera[c].set_exposure(params["exposure"][c]))
        await asyncio.gather(*_)


@define(kw_only=True)
class TestFlowCell(BaseFlowCell):
    name: str = "FlowCell"
    instruments: dict = field(init=False)

    @instruments.default
    def set_instruments(self):
        instruments = {
            "Pump": TestPump(
                name=f"Pump{self.name}", com=COMS_DICT[f"Pump{self.name}"]
            ),
            "Valve": TestValve(
                name=f"Valve{self.name}", com=COMS_DICT[f"Valve{self.name}"]
            ),
            "TemperatureController": TestTemperatureController(
                name=f"TemperatureController{self.name}",
                com=COMS_DICT[f"TemperatureController{self.name}"],
            ),
        }
        return instruments

    async def _configure(self, exp_config):
        """Configure the flowcell."""
        LOGGER.debug(f"Configure {self.name}")


@define
class TestSequencer(BaseSequencer):
    """
    A test sequencer that does not perform any actual sequencing.
    It is used for testing purposes only.
    """

    _flowcells: dict = field(init=False)
    _microscope: TestMicroscope = field(factory=TestMicroscope)

    @_flowcells.default
    def set_flowcells(self):
        return {fc: TestFlowCell(name=fc) for fc in ["A", "B"]}

    # async def _configure(self, exp_config):
    #     LOGGER.debug(f"Configuring {self.name}")

    def custom_roi_stage(self, flowcell: Union[str, int], **kwargs) -> ROIType:
        """Take LLx, LLy, URx, URy coordinates and return stage position parameters."""
        LLx = kwargs.pop("LLx") * 100
        LLy = kwargs.pop("LLy") * 100
        URx = kwargs.pop("URx") * 100
        URy = kwargs.pop("URy") * 100

        # x, y, Steps Per UMicron
        x_spum = self._config["XStage"]["spum"]
        y_spum = self._config["YStage"]["spum"]
        # x, y origin
        x_origin = self._config["XStage"]["origin"][flowcell]
        y_origin = self._config["YStage"]["origin"]
        # x_origin = self.microscope.XStage.config["origin"][fc]
        # y_origin = self.microscope.YStage.config["origin"]

        x_init = LLx * x_spum + x_origin
        x_last = URx * x_spum + x_origin
        y_init = URy * y_spum + y_origin
        y_last = LLy * y_spum + y_origin

        stage = {
            "flowcell": flowcell,
            "x_init": x_init,
            "x_last": x_last,
            "y_init": y_init,
            "y_last": y_last,
        }
        stage.update(kwargs.pop("stage", {}))
        return stage

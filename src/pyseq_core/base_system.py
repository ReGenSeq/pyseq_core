from __future__ import annotations
from abc import ABC, abstractmethod
from pyseq_core.utils import (
    DEFAULT_CONFIG,
    HW_CONFIG,
    setup_experiment_path,
    update_logger,
)
from pyseq_core.base_instruments import (
    BaseInstrument,
    BaseStage,
    BaseShutter,
    BaseFilterWheel,
    BaseLaser,
    BaseCamera,
    BasePump,
    BaseValve,
    BaseTemperatureController,
)
from pyseq_core.base_reagents import ReagentsManager
from pyseq_core.base_protocol import (
    OpticsParams,
    HoldCommand,
    WaitCommand,
    UserCommand,
    TemperatureCommand,
)
from pyseq_core.base_protocol import (
    ROIFactory,
    SimpleStageType,
    PumpCommandFactory,
)
from pyseq_core.base_protocol import (
    read_protocol,
    format_protocol,
    need_reagents,
    check_for_rois,
    read_user_config,
)
from pyseq_core.reservation_system import ReservationSystem, reserve_microscope
from pyseq_core.roi_manager import ROIManager, read_roi_config
from typing import Dict, Union, List, Coroutine, Literal, Type
from attrs import define, field
from pydantic import ValidationError
from pathlib import Path
from warnings import warn
import asyncio
import logging


LOGGER = logging.getLogger("PySeq")

PumpCommand = PumpCommandFactory.factory(DEFAULT_CONFIG)
PumpCommandType = Type[PumpCommand]


ROI = ROIFactory.factory(DEFAULT_CONFIG)
ROIType = Type[ROI]


@define(kw_only=True)
class BaseSystem(ABC):
    name: str = field(default=None)
    instruments: dict = field(factory=dict)
    _queue: asyncio.Queue = field(factory=asyncio.Queue)
    _queue_dict: dict = field(factory=dict)
    _worker_task: asyncio.Task = field(init=False)
    _command_id: int = field(default=0)
    _config: dict = field(init=False)
    _current_task: asyncio.Task = field(default=None)
    _pause_event: asyncio.Event = field(init=False, factory=asyncio.Event)
    _loop_stop: bool = field(init=False, default=False)
    _reservation_system: ReservationSystem = field(init=False)
    # _background_tasks: set = field(init=False, factory=set)

    def __attrs_post_init__(self):
        # Start async worker
        self._worker_task = asyncio.create_task(self._worker())

        # Clear pause event to initially pause queue
        self._pause_event.clear()

        # Getting System Settings
        self._config = HW_CONFIG.get(self.name, HW_CONFIG)

        # Call extra post initialization methods
        self.__extra_post_init__()

    def __extra_post_init__(self):
        pass

    async def _worker(self):
        """Worker function to process the queue."""

        while not self._loop_stop:
            # Wait if queue is paused
            await self._pause_event.wait()

            # Get task
            try:
                id, description, func, args, kwargs = await self._queue.get()
            except asyncio.CancelledError:
                LOGGER.info(f"{self.name} :: Shutting down")
                break

            if not self._queue_dict[id][1]:
                # Check if the task is cancelled
                LOGGER.debug(f"{self.name} :: Task {id} :: {description} cancelled")
            else:
                # Run the task in the event loop

                # Start task

                LOGGER.info(f"{self.name} :: Task {id} :: {description}")
                task_name = "_".join([str(_) for _ in args])
                self._current_task = asyncio.create_task(
                    func(*args, **kwargs), name=task_name
                )

                try:
                    # Wait for the task to finish
                    await self._current_task
                    LOGGER.debug(f"{self.name} :: Task {id} :: {description} finished")
                except asyncio.CancelledError:
                    LOGGER.warning(
                        f"{self.name} :: Task {id} :: {description} cancelled"
                    )
                except Exception:
                    # Check the task status
                    task_exception = self._current_task.exception()
                    LOGGER.exception(
                        f"{self.name} :: Task {id} :: {description}: {task_exception}"
                    )

            # Remove the task from the queue dict
            self._queue_dict.pop(id)
            self._queue.task_done()

        LOGGER.info(f"{self.name} :: Queue stopped")

    def add_task(self, description, func, *args, **kwargs):
        """Add a task to the queue."""

        id = self._command_id
        self._command_id += 1
        self._queue_dict.update({id: [description, True]})
        self._queue.put_nowait([id, description, func, args, kwargs])
        return id

    def cancel_task(self, command_id):
        """Cancel a task in the queue."""
        if command_id in self._queue_dict:
            self._queue_dict[command_id][1] = False
            description = self._queue_dict[command_id][0]
            LOGGER.info(f"{self.name} :: Cancelled task {command_id} :: {description}")
        else:
            LOGGER.warning(f"{self.name} :: Task {command_id} not found")

    async def clear_queue(self):
        for command_id in self._queue_dict:
            self.cancel_task(command_id)
        while self._queue.qsize() > 0:
            await self._queue.get()
            self._queue.task_done()

    def initialize(self):
        """Initialize the system."""
        description = f"Initialize {self.name}"
        self.add_task(description, self._initialize)

    def shutdown(self):
        """Shutdown the system."""
        description = f"Shutdown {self.name}"
        self.add_task(description, self._shutdown)

    def configure(self, exp_config: dict):
        """Configure the system."""
        description = f"Configure {self.name}"
        self.add_task(description, self._configure, exp_config)

    def pause(self):
        """Pause the system queue."""
        LOGGER.info(f"Pausing {self.name}")
        self._pause_event.clear()

    def start(self):
        """Start or unpause the system queue."""
        LOGGER.info(f"Starting {self.name}")
        self._pause_event.set()

    @property
    def condition_lock(self):
        return self._reservation_system.condition_lock

    @property
    def reserved_for(self):
        return self._reservation_system.reserved_for

    @reserved_for.setter
    def reserved_for(self, flowcell: Union[str, None]):
        self._reservation_system.reserved_for = flowcell

    async def _check_pause_and_cancel(
        self, await_task: asyncio.Task, check_cancel: bool = True
    ):
        """Wait if pause event set or exit if current task canceled.
        Optionally if awaiting task is not done, cancel it.
        """

        await asyncio.wait([await_task, self._current_task], asyncio.FIRST_COMPLETED)
        await self.pause_event
        if check_cancel:
            if not self.await_task.done():
                await_task.cancel()

    async def _initialize(self):
        """Connect to instruments, then configure and initialize system."""

        LOGGER.info(f"{self.name} Connecting to instruments")
        _ = []
        for instrument in self.iter_instruments:
            if instrument.com is not None:
                _.append(instrument.com.connect())
        await asyncio.gather(*_)

        LOGGER.info(f"Initializing {self.name}")
        _ = []
        for instrument in self.iter_instruments:
            _.append(instrument.initialize())
        await asyncio.gather(*_)

    async def _shutdown(self):
        """Shutdown the system."""
        LOGGER.info(f"Shutting down {self.name}")

        # Cancel pending tasks
        await self.clear_queue()

        # Shutdown instruments safely
        _ = []
        for instrument in self.iter_instruments:
            _.append(instrument.shutdown())
        await asyncio.gather(*_)

        # Stop worker loop
        self._loop_stop = True

        # Stop work task
        try:
            self._worker_task.cancel()
        except asyncio.CancelledError:
            await self._worker_task

    async def _status(self):
        """Check status all instruments comprising the system."""
        LOGGER.info(f"Checking status of {self.name}")
        _ = []
        for instrument in self.iter_instruments:
            _.append(instrument.status())
        status = await asyncio.gather(*_)
        if all(status):
            return True
        return False

    @abstractmethod
    async def _configure(self, exp_config: dict):
        """Configure the system."""
        pass

    @property
    def iter_instruments(self) -> List[BaseInstrument]:
        _ = []
        for instrument in self.instruments.values():
            if isinstance(instrument, dict):
                # instruments organized in nested dict
                for nest_instrument in instrument.values():
                    _.append(nest_instrument)
            else:
                _.append(instrument)
        return _


@define(kw_only=True)
class BaseMicroscope(BaseSystem):
    name: str = field(default="microscope")
    lock_condition: asyncio.Lock = field(factory=asyncio.Lock)

    @property
    def YStage(self) -> BaseStage:
        """Abstract property for the YStage."""
        return self.instruments.get("YStage", None)

    @property
    def XStage(self) -> BaseStage:
        """Abstract property for the XStage."""
        return self.instruments.get("XStage", None)

    @property
    def ZStage(self) -> BaseStage:
        """Abstract property for the ZStage."""
        return self.instruments.get("ZStage", None)

    @property
    def ObjStage(self) -> BaseStage:
        """Abstract property for the ObjStage."""
        return self.instruments.get("ObjStage", None)

    @property
    def Shutter(self) -> BaseShutter:
        """Abstract property for the Shutter."""
        return self.instruments.get("Shutter", None)

    @property
    def FilterWheel(self) -> Dict[str, BaseFilterWheel]:
        """Abstract property for the FilterWheel.
        Return a dictionary of FilterWheel with their respective laser color lines."""
        return self.instruments.get("FilterWheel", {})

    @property
    def Laser(self) -> Dict[str, BaseLaser]:
        """Abstract property for the lasers.
        Return a dictionary of lasers with their respective colors.
        """
        return self.instruments.get("Laser", {})

    @property
    def Camera(self) -> Dict[str, BaseCamera]:
        """Abstract property for the cameras.
        Return a dictionary of cameras with their respective names.
        """
        return self.instruments.get("Camera", {})

    @abstractmethod
    async def _capture(self, filename):
        """Capture an image and save it to the specified filename."""
        pass

    @abstractmethod
    async def _z_stack(self, start, nsteps, step_size):
        """Perform a z-stack acquisition."""
        pass

    @abstractmethod
    async def _scan(self, roi: ROIType):
        """Perform a scan over the specified region of interest (ROI)."""
        pass

    @abstractmethod
    async def _expose_scan(self, roi: ROIType, duration: Union[float, int]):
        """Scan over the specified region of interest (ROI) with laser."""
        pass

    @abstractmethod
    async def _move(self, roi: ROIType):
        """Move the stage ROI x,y,z coordinates."""
        pass

    @abstractmethod
    async def _set_parameters(
        self, image_params: OpticsParams, mode: Literal["image", "focus", "expose"]
    ):
        """Async set the parameters for the ROI."""
        pass

    @abstractmethod
    async def _find_focus(self, roi: ROIType):
        """Async set the parameters for the ROI."""
        # Reset X & Y stage to initial position after finding focus
        # Save Z stage focus position to `ROI.focus.z_focus`
        # Move Z stage to `ROI.focus.z_focus`
        pass

    @reserve_microscope
    async def _from_flowcell(
        self, routine: Literal["image", "focus", "expose"], roi: List[ROIType]
    ):
        for r in roi:
            if routine in "image":
                self.image(r)
            elif routine in "focus":
                self.focus(r)
            elif routine in "expose":
                self.expose(r)
        await self._queue.join()

    async def _focus(self, roi: ROIType):
        """Async find focus on roi."""
        await self._set_parameters(roi, "focus")
        await self._find_focus(roi)

    async def _expose(self, roi: ROIType):
        """Async expose the sample for a specified duration without imaging."""

        await self._move(roi.stage)
        await self._set_parameters(roi, "expose")
        await self._expose_scan(roi)

    async def _image(self, roi: ROIType) -> None:
        """Async image ROIs."""

        await self._move(roi.stage)
        if roi.focus.z_focus == -1:
            await self._set_parameters(roi, "focus")
            await self._find_focus(roi)
        else:
            await self.ZStage.move(roi.focus.z_focus)
        await self._set_parameters(roi, "image")
        await self._scan(roi)

    def image(self, roi: ROIType) -> None:
        """Acquire image from the specified region of interest (ROI)."""
        description = f"Image {roi.name}"
        return self.add_task(description, self._image, roi)

    def expose(self, roi: ROIType) -> None:
        """Expose the sample to light without imaging."""
        description = f"Expose {roi.name}"
        return self.add_task(description, self._expose, roi)

    def focus(self, roi: ROIType) -> None:
        """Autofocus on ROI."""
        description = f"Focusing on {roi.name}"
        return self.add_task(description, self._focus, roi)

    def move(self, stage: SimpleStageType) -> None:
        """Move the stage ROI x,y,z coordinates."""
        description = f"Move x:{stage.x}, y:{stage.y}, z:{stage.z}"
        return self.add_task(description, self._move, stage)

    def set_parameters(self, roi_params: OpticsParams) -> None:
        """Set the laser power, filters, exposure, imaging mode, etc. for a specified region of interest (ROI)."""
        description = "Setting parameters"
        return self.add_task(description, self._set_parameters, roi_params)


def listerize_roi(func):
    def wrap(self, roi: Union[ROIType, List[ROIType]] = []):
        if not isinstance(roi, list):
            roi = [roi]
        if len(roi) == 0:
            roi = list(self.ROIs.values())
        return func(self, roi)

    return wrap


@define(kw_only=True)
class BaseFlowCell(BaseSystem):
    _roi_to_microscope: Coroutine = field(init=False)
    reagents: dict = field(factory=dict)
    ROIs: dict = field(init=False, factory=dict)
    # enabled: bool = True
    _exp_config: dict = field(default=None)
    _protocol_name: str = field(default="")
    _protocol_cycle: int = field(default=1)

    @property
    def Pump(self) -> BasePump:
        """Abstract property for the pump."""
        return self.instruments.get("Pump", None)

    @property
    def Valve(self) -> BaseValve:
        """Abstract property for the pump."""
        return self.instruments.get("Valve", None)

    @property
    def TemperatureController(self) -> BaseTemperatureController:
        """Abstract property for the pump."""
        return self.instruments.get("TemperatureController", None)

    def select_port(self, reagent: Union[int, str]):
        """Select a port on the valve."""

        if isinstance(reagent, str):
            if reagent in self.reagents:
                port = self.reagents[reagent]["port"]
            else:
                return False
        elif isinstance(reagent, int):
            port = reagent

        description = f"Select {reagent} at port {port}."
        self.add_task(description, self.Valve.select, port)
        return True

    def pump(
        self,
        volume: Union[int, float],
        flow_rate: Union[int, float] = 0,
        reagent: Union[int, str] = None,
        reverse: bool = False,
        **kwargs,
    ) -> int:
        """Pump volume in uL from port at flow rate in uL/min."""

        if reagent is not None:
            if not self.select_port(reagent):
                raise KeyError(f"{reagent} is invalid for Valve {self.name}")

        if flow_rate == 0:
            flow_rate = self.reagents[reagent].get("flow_rate")

        if not reverse:
            description = f"Pump {volume} uL at {flow_rate} uL/min."
            return self.add_task(
                description, self.Pump.pump, volume, flow_rate, **kwargs
            )
        else:
            return self.reverse_pump(volume, flow_rate, **kwargs)

    def reverse_pump(
        self,
        volume: Union[int, float],
        flow_rate: Union[int, float],
        port: Union[int, str] = None,
        **kwargs,
    ) -> int:
        """Pump volume in uL from waste to port at flow rate in uL/min."""

        if port is not None:
            self.select_port(port)

        description = f"Reverse pump {volume} uL at {flow_rate} uL/min."
        return self.add_task(
            description, self.Pump.reverse_pump, volume, flow_rate, **kwargs
        )

    def hold(self, duration: Union[int, float]) -> None:
        """Hold for specified duration (minutes)."""
        description = f"Hold for {duration} minutes."
        return self.add_task(description, self._hold, duration)

    def wait(self, event: str) -> int:
        """Wait for microscope or flowcell event."""
        description = f"Wait for {event}."
        return self.add_task(description, self._wait, event)

    def user(self, message: str, timeout: Union[float, None]) -> None:
        """Send message to the user and wait for a response."""
        description = "Wait for user response"
        return self.add_task(description, self._user_wait, message, timeout)

    def temperature(
        self, temperature: Union[int, float], timeout: Union[float, None]
    ) -> None:
        """Set the temperature of the flow cell."""
        description = f"Set temperature to {temperature} C"
        return self.add_task(
            description,
            self.TemperatureController.set_temperature,
            temperature,
            timeout,
        )

    @listerize_roi
    def image(self, roi: Union[ROIType, List[ROIType]] = []) -> int:
        """Image specified ROIs or all ROIs on flowcell (default)."""
        description = f"Image {len(roi)} ROIs"
        self.add_task(description, self._roi_to_microscope, "image", roi)

    @listerize_roi
    def focus(self, roi: Union[ROIType, List[ROIType]] = []) -> int:
        """Focus on specified ROIs or all ROIs on flowcell (default)."""
        description = f"Focus on {len(roi)} ROIs"
        self.add_task(description, self._roi_to_microscope, "focus", roi)

    @listerize_roi
    def expose(self, roi: Union[ROIType, List[ROIType]] = []) -> int:
        """Expose specified ROIs or all ROIs on flowcell (default)."""
        description = f"Expose {len(roi)} ROIs"
        self.add_task(description, self._roi_to_microscope, "expose", roi)

    def update_protocol_name(self, name: str):
        """Queue a task to update the protocol name."""
        description = f"Start protocol {name}"
        self.add_task(description, self._update_protocol_name, name)

    def _update_protocol_name(self, name: str):
        self._protocol_name = name
        self._protocol_cycle = 0

    def update_protocol_cycle(self, cycle: int, total_cycles: int, protocol_name: str):
        """Queue a task to update the protocol cycle."""
        if total_cycles > 1:
            description = (
                f"Start cycle {cycle}/{total_cycles} of protocol {protocol_name}"
            )
            self.add_task(description, self._update_protocol_cycle)

    def _update_protocol_cycle(self):
        self._protocol_cycle += 1

    async def _hold(self, duration):
        """Async hold for specified duration in minutes."""

        await asyncio.sleep(duration * 60)

    async def _wait(self, event: str):
        """Async wait for an event"""

        if event == "microscope":
            async with self.condition_lock:
                await self.condition_lock.wait_for(lambda: self.reserved_for is None)
            self.reserved_for = self.name

    async def _user_wait(self, message, timeout=None):
        """Async send message to the user and wait for a response."""

        await asyncio.wait_for(asyncio.to_thread(input, message), timeout)


def get_roi(func):
    def wrap(
        self,
        roi: Union[ROIType, List[ROIType]] = [],
        flowcells: Union[str, List[str]] = None,
        **kwargs,
    ):
        if isinstance(roi, list) and len(roi) == 0 and len(kwargs) == 0:
            # image/expose/focus ROIs listed on flowcells
            for fc in self._get_systems_list(flowcells):
                func(self, roi, fc.name)
            return
        elif not isinstance(roi, list) and len(kwargs) == 0:
            # put single ROI in list
            roi = [roi]
        elif len(kwargs) > 0:
            # put single ROI specified by kwargs into list
            roi = [ROI(**kwargs)]

        # split ROIs into lists for specific flowcells
        _rois = {}
        for r in roi:
            _rois.set_default(r.stage.flowcell, [])
            _rois[r.stage.flowcell].append(r)
        # image/expose/focus ROIs in list
        for fc, fc_rois in _rois.items():
            func(self, fc_rois, fc)

    return wrap


@define
class BaseSequencer(BaseSystem):
    _microscope: BaseMicroscope = field(init=False)
    _flowcells: dict[Union[str, int], BaseFlowCell] = field(init=False)
    _reagents_manager: ReagentsManager = field(init=False)
    _roi_manager: ROIManager = field(init=False)
    _sys_dict: dict = field(init=False)
    # _enable: dict = field(factory=dict)

    @property
    def microscope(self) -> BaseMicroscope:
        """Abstract property for the microscope."""
        return self._microscope

    @property
    def flowcells(self) -> Dict[str, BaseFlowCell]:
        """Abstract property for the flow cells.
        Return a dictionary of flow cells with their respective names.
        """
        return self._flowcells

    def __extra_post_init__(self):
        # Set up microscope reservation system
        rez_sys = ReservationSystem()
        self._microscope._reservation_system = rez_sys

        # Add reagents manager
        self._reagents_manager = ReagentsManager(self._flowcells)

        # Add ROI manager
        self._roi_manager = ROIManager(self._flowcells)

        # Connect microscope to flow cells
        for fc in self._flowcells.keys():
            self._flowcells[fc]._roi_to_microscope = self._microscope._from_flowcell
            self._flowcells[fc]._reservation_system = rez_sys
            # self._enable[fc] = True

        self._pause_event.set()

    @abstractmethod
    @_flowcells.default
    def set_flowcells(self):
        # return {fc: TestFlowCell(name=fc) for fc in ["A", "B"]}
        pass

    def pump(
        self,
        flowcells: Union[str, int] = None,
        pump_command: PumpCommandType = None,
        **kwargs,
    ):
        """Pump volume in uL from/to specified port at flow rate in ul/min on specified flow cell."""
        fc_ = self._get_systems_list(flowcells)

        task_ids = []
        for fc in fc_:
            if pump_command is None:
                kwargs.update({"flowcell": fc.name})
                pump_command = PumpCommand(**kwargs)
            pump_kwargs = pump_command.model_dump()
            del pump_kwargs["flowcell"]
            task_ids.append(fc.pump(**pump_kwargs))
        return task_ids

    def hold(
        self,
        flowcells: Union[str, int] = None,
        hold_command: HoldCommand = None,
        **kwargs,
    ) -> Union[int, List[int]]:
        """Hold specified flow cell for specified duration in minutes, used for incubations."""

        if hold_command is None:
            hold_command = HoldCommand(**kwargs)
        fc_ = self._get_systems_list(flowcells)
        task_ids = []
        for fc in fc_:
            task_ids.append(fc.hold(hold_command.duration))
        return task_ids

    def wait(
        self,
        flowcells: Union[str, int] = None,
        wait_command: WaitCommand = None,
        **kwargs,
    ) -> Union[int, List[int]]:
        """Specified flow cell waits for microscope before continuing."""

        if wait_command is None:
            wait_command = WaitCommand(**kwargs)
        fc_ = self._get_systems_list(flowcells)
        task_ids = []
        for fc in fc_:
            task_ids.append(fc.wait(wait_command.event))
        return task_ids

    def user(
        self,
        flowcells: Union[str, int] = None,
        user_command: UserCommand = None,
        **kwargs,
    ) -> Union[int, List[int]]:
        """Specified flow cell waits for microscope before continuing."""

        if user_command is None:
            user_command = UserCommand(**kwargs)
        fc_ = self._get_systems_list(flowcells)
        task_ids = []
        for fc in fc_:
            task_ids.append(fc.user(user_command.message, user_command.timeout))
        return task_ids

    def temperature(
        self,
        flowcells: Union[str, int] = None,
        temperature_command: TemperatureCommand = None,
        **kwargs,
    ):
        """Hold specified flow cell for specified duration in minutes, used for incubations."""
        fc_ = self._get_systems_list(flowcells)
        task_ids = []
        for fc in fc_:
            if temperature_command is None:
                kwargs.update({"flowcell": fc.name})
                temperature_command = TemperatureCommand(**kwargs)
            temperature_kwargs = temperature_command.model_dump()
            del temperature_kwargs["flowcell"]
            task_ids.append(fc.temperature(**temperature_kwargs))
        return task_ids

    @get_roi
    def image(
        self,
        roi: Union[ROIType, List[ROIType]] = [],
        flowcells: Union[str, List[str]] = None,
        **kwargs,
    ):
        """Image ROIs."""
        self.flowcells[flowcells].image(roi)

    @get_roi
    def focus(
        self,
        roi: Union[ROIType, List[ROIType]] = [],
        flowcells: Union[str, List[str]] = None,
        **kwargs,
    ):
        """Find focus z position in ROIs."""
        self.flowcells[flowcells].focus(roi)

    @get_roi
    def expose(
        self,
        roi: Union[ROIType, List[ROIType]] = [],
        flowcells: Union[str, List[str]] = None,
        **kwargs,
    ):
        """Expose ROIs to light without imaging."""
        self.flowcells[flowcells].expose(roi)

    async def _initialize(self, systems: Union[str, List[str]] = []):
        """Connect to and initiliaze instruments in flow cell, microscope or entire sequencer (default)."""

        _systems = self._get_systems_list(systems)
        _ = []
        for s in _systems:
            s.initialize()
            _.append(s._queue.join())
        await asyncio.gather(*_)

    async def _configure(self, exp_config: dict, systems: Union[str, List[str]] = []):
        """Configure instruments in flow cell, microscope or entire sequencer (default)."""

        _systems = self._get_systems_list(systems)
        _ = []
        for s in _systems:
            s.configure(exp_config)
            _.append(s._queue.join())
        await asyncio.gather(*_)

    def pause(self, systems: Union[str, List[str]] = []):
        """Pause flow cell, microscope, or entire sequencer (default)."""

        # Check user supplied queues
        _systems = self._get_systems_list(systems)
        for s in _systems:
            s.pause()
        if len(systems) == 0:
            self._pause_event.clear()

    def start(self, systems: Union[str, List[str]] = []):
        """Start flow cell, microscope, or entire sequencer (default)."""

        # Check user supplied queues
        _systems = self._get_systems_list(systems)
        for s in _systems:
            s.start()
        if len(systems) == 0:
            self._pause_event.set()

    def shutdown(self, systems: Union[str, List[str]] = []):
        """Shutdown flow cell, microscope, or entire sequencer (default)."""

        # Check user supplied queues
        _systems = self._get_systems_list(systems)
        for s in _systems:
            s.shutdown()
        # if len(systems) == 0:
        #     self._loop_stop = True

    def _get_systems_list(
        self, systems: Union[str, List[str, int]] = []
    ) -> List[Union[BaseMicroscope, BaseFlowCell]]:
        """Return list of valid flow cell and microscope systems."""

        fc_list = [fc for fc in self._flowcells.values()]

        # Return all systems, flowcells, or microscopes
        if systems is None:
            return fc_list
        elif len(systems) == 0:
            return fc_list + [self._microscope]
        elif "flowcell" in systems:
            return fc_list
        elif "micro" in systems or "scope" in systems:
            return [self._microscope]
        elif isinstance(systems, str) and len(systems) <= len(fc_list):
            # Assume string of flowcells for example "AB" = ["A", "B"]
            systems = [s.upper() for s in systems]
        elif isinstance(systems, int):
            # input is flow cell referenced by number
            systems = [systems]
        elif isinstance(systems, list):
            # input is list
            systems = [
                s.upper() if isinstance(s, str) and len(s) == 1 else s for s in systems
            ]

        systems_ = []
        for s in systems:
            if s in self._flowcells.keys():
                systems_.append(self._flowcells[s])
            elif "micro" in s.lower() or "scope" in s.lower():
                systems_.append(self._microscope)
            else:
                raise ValueError(f"{s} is not a valid flow cell or microscope.")

        return systems_

    # def _get_fc_list(self, fc: Union[str, list] = None) -> List[BaseFlowCell]:
    #     """Return list of valid running flowcells.
    #     """

    #     if fc is None:
    #         return [fc for fc in  self.flowcells.values() if fc._pause_event.is_set()]
    #     elif isinstance(fc, str) and len(fc) == 1:
    #         # fc = 'A' or 'B'
    #         fc = [fc]
    #     # else: fc = 'AB' or ['A', 'B']
    #     fc_ = [_.upper() for _ in fc]

    #     # Check user supplied flow cell names
    #     fcs = []
    #     for fc in fc_:
    #         if fc not in self._flowcells:
    #             raise ValueError(f"{fc} is not a valid flow cell.")
    #         elif not self._flowcells[fc]._pause_event.is_set():
    #             raise ValueError(f"Flow cell {fc} is paused.")
    #         else:
    #             fcs.append(self._flowcells[fc])

    #     return fcs

    # @property
    # def enable(self):
    #     """Get the enabled status of the flowcells."""
    #     return self._enable

    # @enable.setter
    # def enable(self, flowcells: Union[str, list]):
    #     """Toggle flowcells to be enabled/disabled"""
    #     for fc in self._get_fc_list(flowcells):
    #         status = not self._flowcells[fc].enable
    #         self._flowcells[fc].enabled = status
    #         self._enable[fc] = status

    # @property
    # def enabled_flowcells(self):
    #     """Get the list of only enabled flowcells."""
    #     return [fc for fc in self._flowcells.values() if fc.enabled]

    def add_rois(self, fc_names: str, roi_path: str) -> int:
        flowcells = self._get_systems_list(fc_names)

        # Read roi file and get list of validated ROIs
        try:
            rois = read_roi_config(
                fc_names,
                roi_path,
                flowcells[0]._exp_config,
                self.custom_roi_stage,
            )
        except ValidationError as e:
            LOGGER.error(e)
            return 0

        # Add rois to flowcells, keep track if error adding roi to flowcell
        was_roi_added = []
        for roi in rois:
            was_roi_added.append(self._roi_manager.add(roi))
        # Wake up flowcells waiting for ROIs if no errors
        if self._roi_manager.roi_condition.locked() and all(was_roi_added):
            self._roi_manager.roi_condition.notify_all()

        return sum(was_roi_added)

    def new_experiment(
        self, fc_names: Union[str, int], exp_config_path: str, exp_name: str
    ):
        """Load new experimenet from config file for specified flowcells"""
        # Pause flowcells
        flowcells = self._get_systems_list(fc_names)
        for fc in flowcells:
            if not fc._queue.empty():
                raise RuntimeError(
                    f"Flow cell {fc.name} still running, stop flow cell before starting new experiment"
                )
            else:
                fc.pause()
        # Load new experiment
        description = "Load new experiment"
        self.add_task(description, self._new_experiment, fc_names, exp_config_path)

    async def _new_experiment(
        self, fc_names: Union[str, int], exp_config_path: str, exp_name: str = ""
    ):
        """Load new experiment task."""

        # Read experiment config
        exp_config = read_user_config(exp_config_path)
        # Set up paths for imaging, focusin, and logging and update exp_config
        exp_config = setup_experiment_path(exp_config, exp_name)
        (
            update_logger(
                exp_config["logging"], exp_config["rotate_logs"]["rotate_logs"]
            ),
        )

        # Reset rois and reagents
        flowcells = self._get_systems_list(fc_names)
        for fc in flowcells:
            fc._exp_config = exp_config
            fc.ROIs = dict()
            fc.reagents = dict()

        await self._configure(exp_config)

        # Add reagents from experiment config to flowcells
        for fc in flowcells:
            self._reagents_manager.add_from_config(fc.name, exp_config)

        # Add ROIs from experiment config to flowcels
        roi_path = Path(exp_config["experiment"].get("roi_path", "."))
        if roi_path.is_file():
            LOGGER.info(f"Adding ROIs from {roi_path}")
            n_rois_added = self.add_rois(fc_names, roi_path)
            LOGGER.info(f"Added {n_rois_added} ROIs")

        # Read protocol from experiment config
        protocol = read_protocol(exp_config["experiment"]["protocol_path"])
        fprotocol = {}
        for fc in flowcells:
            protocol = read_protocol(exp_config["experiment"]["protocol_path"])
            fprotocol[fc.name] = format_protocol(fc.name, protocol, exp_config)

        # Check if reagents are needed
        for fc in flowcells:
            missing_reagents = need_reagents(fprotocol[fc.name], fc.reagents)
            if missing_reagents > 0:
                raise ValueError(
                    f"Missing {missing_reagents} reagents for flowcell {fc.name}"
                )

        # Check status of systems
        _ = []
        for s in self._get_systems_list():
            _.append(s._status())
        _.append(self._status())
        status = await asyncio.gather(*_)
        if all(status):
            all_systems_go = True
        else:
            warn("Some systems are not ready")
            # TODO: get user confirmation to proceed if there are system issues
            all_systems_go = True

        if all_systems_go:
            # Check if ROIs needed -> wait for ROIs if none in config
            for fc in flowcells:
                # if not check_for_rois(fprotocol[fc.name]) and len(fc.ROIs) == 0:
                if not check_for_rois(fprotocol[fc.name]):
                    await self._roi_manager.wait_for_rois(fc.name)

        # Add steps from protocol to queues
        for fc in flowcells:
            description = f"Queue protocol on {fc.name}"
            self.add_task(
                description, self._queue_protocol, fc.name, fprotocol[fc.name]
            )
            # self._queue_protocol(fc.name, fprotocol[fc.name])

    async def _queue_protocol(self, flowcell: Union[str, int], fprotocols: dict):
        for pname, protocol in fprotocols.items():
            LOGGER.info(f"Queueing protocol {pname} on flowcell {flowcell}")
            self.flowcells[flowcell].update_protocol_name(pname)
            for cycle in range(protocol["cycles"]):
                self.flowcells[flowcell].update_protocol_cycle(
                    cycle + 1, protocol["cycles"], pname
                )
                for step in protocol["steps"]:
                    LOGGER.debug(f"Added {step[0]}, {step[1]} on flowcell {flowcell}")
                    params = step[1]
                    if "PUMP" in step[0]:
                        self.pump(flowcells=flowcell, **params)
                    elif "HOLD" in step[0]:
                        self.hold(flowcells=flowcell, **params)
                    elif "WAIT" in step[0]:
                        self.wait(flowcells=flowcell, event=params["event"])
                    elif "USER" in step[0]:
                        self.user(flowcells=flowcell, **params)
                    elif "IMAG" in step[0]:
                        if "stage" in params:
                            self.image(flowcells=flowcell, **params)
                        else:
                            self.image(flowcells=flowcell)
                    elif "EXPO" in step[0]:
                        if "stage" in params:
                            self.expose(flowcells=flowcell, **params)
                        else:
                            self.expose(flowcells=flowcell)

    @abstractmethod
    def custom_roi_stage(flowcell: Union[str, int], **kwargs) -> dict:
        pass

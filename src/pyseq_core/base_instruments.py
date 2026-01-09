from __future__ import annotations
from abc import ABC, abstractmethod
from pyseq_core.utils import HW_CONFIG
from pyseq_core.base_com import BaseCOM
from attrs import define, field
from typing import Union
from functools import cached_property
import asyncio


@define()
class BaseInstrument(ABC):
    name: str = field()
    com: BaseCOM = field(default=None)

    """
    Abstract base class for instrument implementations.

    This class defines the interface that all instrument classes must implement.
    Subclasses should provide concrete implementations for all abstract methods.

    Attributes:
        name (str): The name of the instrument.
        com (BaseCOM): The communication interface for the instrument.
    """

    @property
    def connected(self) -> bool:
        return self.com._connected

    @cached_property
    def config(self) -> dict:
        return HW_CONFIG[self.name]

    def connect(self) -> bool:
        return self.com.connect()

    async def command(self, command: Union[str, dict], **kwargs):
        """Send a command string to the instrument.

        This method forwards the given command to the instrument's communication
        interface (`self.com`).

        Args:
            command (str, dict): The command string to send to the instrument.

        Returns:
            str,dict: The response received from the instrument's communication interface.
        """
        return await self.com.command(command, **kwargs)

    @abstractmethod
    async def initialize(self):
        """
        Initialize the instrument.

        This method should be implemented by subclasses to perform any setup
        required before the instrument can be used, such as configuring hardware.

        Raises:
            NotImplementedError: If the subclass does not implement this method.
        """

    @abstractmethod
    async def shutdown(self):
        """Shutdown the instrument.

        This method should be implemented by subclasses to gracefully
        shutdown the instrument, releasing resources, or putting the hardware
        into a safe state.
        """

    @abstractmethod
    async def status(self) -> bool:
        """Retrieve the current operational status of the instrument.

        This method should be implemented by subclasses to query the instrument
        and determine its current state.

        Returns:
            bool: True if the instrument is operational and ready for use,
                False otherwise.
        """

    @abstractmethod
    async def configure(self, exp_config: dict):
        """Configure the instrument.

        This method should be implemented by subclasses to apply specific
        configuration settings to the instrument, typically based on the
        `self.config` attribute. This might involve sending commands to the
        hardware to set parameters or modes of operation.
        """


@define
class BaseStage(BaseInstrument):
    _position: Union[int, float] = field(init=False)
    """
    Abstract base class for a microscope stage instrument.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for controlling a stage, such as moving to a position
    and retrieving the current position.

    Attributes:
        _position (Union[int, float]): The cached current position of the stage.
            This attribute is not initialized directly but is set by the `position` setter.
    """

    @cached_property
    def min_position(self) -> Union[float, int]:
        """The minimum allowed position for the stage.

        This value is retrieved from the instrument's configuration settings
        under the key "min_val".

        Returns:
            Union[float, int]: The minimum position.
        """
        return self.config.get("min_val")

    @cached_property
    def max_position(self) -> Union[float, int]:
        """The maximum allowed position for the stage.

        This value is retrieved from the instrument's configuration settings
        under the key "max_val".

        Returns:
            Union[float, int]: The maximum position.
        """
        return self.config.get("max_val")

    @abstractmethod
    async def move(self, positiion):
        """Move the stage to a specified position.

        This method should be implemented by subclasses to send commands to the
        physical stage to move it to the target position.

        Args:
            positiion (Union[int, float]): The target position to move the stage to.
        """

    @abstractmethod
    async def get_position(self):
        """Retrieve the current actual position of the stage.

        This method should be implemented by subclasses to query the physical
        stage for its current position and save it with the `position` setter.

        Returns:
            Union[int, float]: The current position of the stage.
        """
        pass

    @property
    def position(self):
        """Cached stage position.

        This property provides access to the internally stored position of the stage.
        It does not query the physical hardware.

        Returns:
            Union[int, float]: The cached current position of the stage.
        """
        return self._position

    @position.setter
    def position(self, position):
        """Set the current cached position of the stage.

        This setter updates the internal `_position` attribute. It does not
        move the physical stage; for that, use the `move` method.

        Args:
            position (Union[int, float]): The new position value to cache.
        """
        self._position = position


@define
class BasePump(BaseInstrument):
    """
    Abstract base class for a pump instrument.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for controlling a pump, such as dispensing liquid
    at a specified volume and flow rate.
    """

    @cached_property
    def min_volume(self) -> Union[float, int]:
        """The minimum allowed volume for the pump.

        This value is retrieved from the instrument's configuration settings
        under the "volume" section and "min_val" key.

        Returns:
            Union[float, int]: The minimum volume.
        """
        return self.config.get("volume").get("min_val", 1)

    @cached_property
    def max_volume(self) -> Union[float, int]:
        """The maximum allowed volume for the pump.

        This value is retrieved from the instrument's configuration settings
        under the "volume" section and "max_val" key.

        Returns:
            Union[float, int]: The maximum volume.
        """
        return self.config.get("volume").get("max_val", 2000)

    @cached_property
    def min_flow_rate(self) -> Union[float, int]:
        """The minimum allowed flow rate for the pump.

        This value is retrieved from the instrument's configuration settings
        under the "flow_rate" section and "min_val" key.

        Returns:
            Union[float, int]: The minimum flow rate.
        """
        return self.config.get("flow_rate").get("min_val", 100)

    @cached_property
    def max_flow_rate(self) -> Union[float, int]:
        """The maximum allowed flow rate for the pump.

        This value is retrieved from the instrument's configuration settings
        under the "flow_rate" section and "max_val" key.

        Returns:
            Union[float, int]: The maximum flow rate.
        """
        return self.config.get("flow_rate").get("max_val", 20000)

    @abstractmethod
    async def pump(
        self, volume: Union[float, int], flow_rate: Union[float, int], **kwargs
    ):
        """Pump a specified volume at a specified flow rate from inlet to outlet of flowcell.

        This method should be implemented by subclasses to control the physical
        pump to dispense a given volume of liquid at a particular flow rate.

        Args:
            volume (Union[float, int]): The volume of liquid to pump.
            flow_rate (Union[float, int]): The rate at which to pump the liquid.
            **kwargs: Additional keyword arguments that might be specific to
                      a particular pump implementation (e.g., pause_time, waste_flow_rate).
        Returns:
            bool: True if succesfully pumped volume, otherwise False.
        """

    @abstractmethod
    async def reverse_pump(
        self, volume: Union[float, int], flow_rate: Union[float, int], **kwargs
    ):
        """Pump a specified volume at a specified flow rate from outlet to inlet of flowcell.

        This method should be implemented by subclasses to control the physical
        pump to withdraw a given volume of liquid at a particular flow rate.

        Args:
            volume (Union[float, int]): The volume of liquid to reverse pump.
            flow_rate (Union[float, int]): The rate at which to reverse pump the liquid.
            **kwargs: Additional keyword arguments that might be specific to
                      a particular pump implementation.
        Returns:
            bool: True if succesfully pumped volume, otherwise False.
        """
        pass


@define
class BaseValve(BaseInstrument):
    _port: Union[str, int] = field(init=False)
    # ports: List[int] = field(init=False)
    """
    Abstract base class for a valve instrument.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for controlling a valve, such as selecting a port
    and reading the current port.

    Attributes:
        _port (Union[str, int]): The cached current port of the valve.
            This attribute is not initialized directly but is set by the `port` setter
            or `initial_port_value` default.
    """

    @abstractmethod
    async def select(self, port: Union[str, int], **kwargs) -> bool:
        """Select a specific port on the valve.

        This method should be implemented by subclasses to send commands to the
        physical valve to switch to the specified port.

        Args:
            port (Union[str, int]): The name or position of the port to select.
            **kwargs: Additional keyword arguments that might be specific to
                      a particular valve implementation (e.g., speed, timeout).
        Returns:
            bool: True if succesfull select port, otherwise False.
        """

    @abstractmethod
    async def current_port(self) -> Union[str, int]:
        """Read the current active port from the valve.

        This method should be implemented by subclasses to query the physical
        valve and retrieve its currently selected port.

        Returns:
            Union[str, int]: The identifier of the current active port.
        """
        pass

    # @ports.default
    # def default_ports(self):
    #     self.config["port"]["valid_list"]

    @cached_property
    def ports(self):
        """A list of valid ports supported by the valve.

        This value is retrieved from the instrument's configuration settings
        under the "valid_list" key.

        Returns:
            list[Union[str, int]]: A list of valid port identifiers.
        """
        return self.config.get("valid_list", [])

    @property
    def port(self):
        """Get the current cached port of the valve.

        This property provides access to the internally stored port of the valve.
        It does not query the physical hardware.

        Returns:
            Union[str, int]: The cached current port of the valve.
        """
        return self._port

    @port.setter
    def port(self, port):
        """Set the current cached port of the valve.

        This setter updates the internal `_port` attribute. It does not
        select the physical port; for that, use the `select` method.

        Args:
            port (Union[str, int]): The new port value to cache.
        """
        self._port = port


@define
class BaseLaser(BaseInstrument):
    color: str = field(default=None)
    _power: Union[int, float] = field(init=False)

    """Abstract base class for laser instruments.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for controlling a laser, such as setting and reading the 
    laser power.

    Attributes:
        color (str): The color of the laser beam (e.g., "red", "green", "blue").
        _power (Union[int, float]): The current cached power setting of the 
            laser. This attribute is not initialized directly but is set by the 
            `power` setter.
    """

    @cached_property
    def min_power(self):
        """Returns the minimum allowed power for the laser.

        This value is retrieved from the instrument's configuration, defaulting
        to 0 if not specified.

        Returns:
            Union[int, float]: The minimum power value.
        """
        return self.config.get("min_val", 0)

    @cached_property
    def max_power(self):
        """Returns the maximum allowed power for the laser.

        This value is retrieved from the instrument's configuration, defaulting
        to 100 if not specified.

        Returns:
            Union[int, float]: The maximum power value.
        """
        return self.config.get("max_val", 100)

    @abstractmethod
    async def set_power(self, power):
        """Sets the power of the laser.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the laser's power is physically adjusted.

        Args:
            power (Union[int, float]): The desired power level to set.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

    @abstractmethod
    async def get_power(self):
        """Retrieves the current power of the laser.

        This is an abstract asynchronous method that must be implemented by subclasses to
        define how the laser's current power setting is read, and then saved to
        _power.

        Returns:
            Union[int, float]: The current power level of the laser.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

    @property
    def power(self):
        """The current cached power setting of the laser.

        This property provides read-only access to the laser's cached power.
        To change the power, use the `set_power` method.

        Returns:
            Union[int, float]: The current power level.
        """
        return self._power


@define
class BaseFilter(BaseInstrument):
    _filters: dict = field(init=False)
    _filter: Union[float, str] = field(init=False)
    """Abstract base class for optical filter instruments.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for selecting a filter from a filter wheel or moving a filter
    in place.

    Attributes:
        _filters (dict): A dictionary mapping filter names to their positions on
            the filter wheel
        _filter (Union[float, str]): The cached currently selected filter on the 
            wheel.
    """

    def __attrs_post_init__(self):
        """Post-initialization hook for attrs.

        This method is called automatically after the instance is initialized.
        It populates the `_filters` attribute with the list of valid filters
        retrieved from the instrument's configuration.
        """
        self._filters = self.config.get("valid_list")

    @abstractmethod
    async def set_filter(self, filter: Union[float, str]):
        """Selects a specific filter on the wheel.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the filter wheel physically moves to the
        desired filter and saves the filter to `_filter`.

        Args:
            filter (Union[float, str]): The identifier of the filter to select.
                This could be a filter name (str) or an index (float/int).

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        pass

    @abstractmethod
    async def get_filter(self):
        """Get postion of filter wheel.

        This is an abstract asynchronous method that must be implemented by
        subclasses to read the position of the filter wheel and saves the position
        to `_filter`.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        pass

    @property
    def filter(self):
        """The currently selected filter on the wheel.

        This property provides read-only access to the cached value of the
        currently active filter. To change the filter, use the `set_filter`
        method.

        Returns:
            Union[float, str]: The identifier of the currently active filter.
        """
        return self._filter


@define
class BaseShutter(BaseInstrument):
    _open: bool = field(init=False)

    """Abstract base class for shutter instruments.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for opening/closing a shutter.

    Attributes:
        _open (bool): An cached attribute indicating whether the shutter is
            currently open (`True`) or closed (`False`). This should be accessed
            via the `open` property.
    """

    @abstractmethod
    async def open(self):
        """Moves the shutter to either an open or closed position.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the shutter physically transitions to the
        specified state, and saves the open state (True/False) to `_open`.

        Args:
            open (bool): If `True`, the shutter will move to the open position.
                If `False`, it will move to the closed position.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

    @abstractmethod
    async def close(self):
        """Closes the shutter.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the shutter physically closes and then sets
        `_open` = False.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

    @property
    def is_open(self):
        """The cached current position of the shutter.

        This property provides read-only access to the cached state of whether
        the shutter is open or closed.

        Returns:
            bool: `True` if the shutter is open, `False` if it is closed.
        """
        return self._open


class BaseCamera(BaseInstrument):
    _exposure: float = field(init=False)

    """Abstract base class for camera instruments.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for cameras such as taking and saving an image.

    Attributes:
        _exposure (float): The current exposure time setting for the camera in
            seconds. This is an cached attribute and should be accessed via
            the `exposure` property.
    """

    @abstractmethod
    async def capture(self):
        """Captures an image using the camera.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the camera acquires an image. Captured images
        are assumed to be stored in the camera's internal memory.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

    @abstractmethod
    async def save_image(self, dirpath):
        """Saves the captured image to a specified directory.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the captured image data is written to disk.

        Args:
            dirpath (str): The full path including the filename and extension
                where the image should be saved.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        pass

    @abstractmethod
    async def set_exposure(self, time):
        """Sets the exposure time for the camera.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the camera's exposure time is physically
        adjusted.

        Args:
            time (float): The desired exposure time in seconds.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        pass

    @abstractmethod
    async def get_exposure(self, time):
        """Retrieves the current exposure time from the camera.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the camera's current exposure time is read and
        then saved to `_exposure`.

        Returns:
            float: The current exposure time in seconds.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        pass

    @property
    def exposure(self):
        """The current cached exposure time of the camera.

        This property provides read-only access to the cached value of the
        camera's exposure time. To change the exposure, use the `set_exposure`
        method.

        Returns:
            float: The current exposure time in seconds.
        """
        self._exposure

    @cached_property
    def min_exposure(self):
        """Returns the minimum allowed exposure time for the camera.

        This value is retrieved from the instrument's configuration.

        Returns:
            Union[int, float, None]: The minimum exposure time value, or None
                if not specified in the configuration.
        """
        return self.config.get("min_val")

    @cached_property
    def max_exposure(self):
        """Returns the maximum allowed exposure time for the camera.

        This value is retrieved from the instrument's configuration.

        Returns:
            Union[int, float, None]: The maximum exposure time value, or None
                if not specified in the configuration.
        """
        return self.config.get("max_val")


@define
class BaseTemperatureController(BaseInstrument):
    _temperature: Union[float, int] = field(init=False)

    """Abstract base class for camera instruments.

    This class extends `BaseInstrument` to define common properties and
    abstract methods for temperature controllers such as setting and reading 
    temperatures.

    Attributes:
        _temperature Union[float, int] : The current temperature set point for the temperature controller in
            degrees Celsius. This is an cached attribute and should be accessed via
            the `temperature` property.
    """

    @cached_property
    def min_temperature(self):
        """Returns the minimum allowed temperature for the temperature controller.

        This value is retrieved from the instrument's configuration.

        Returns:
            Union[int, float, None]: The minimum temperature value, or None
                if not specified in the configuration.
        """
        return self.config.get("min_val")

    @cached_property
    def max_temperature(self):
        """Returns the maximum allowed temperature for the temperature controller.

        This value is retrieved from the instrument's configuration.

        Returns:
            Union[int, float, None]: The maximum temperature value, or None
                if not specified in the configuration.
        """
        return self.config.get("max_val")

    # Don't use property setter, can't use explicity with async
    # ie can't do `await temperature = t`
    @abstractmethod
    async def set_temperature(
        self, temperature: float, timeout: Union[float, None] = 0.0
    ):
        """Sets the temperature set point for the temperature controller.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the temperature setpoint is physically
        adjusted. If `timeout` is not None, then wait for `timeout` seconds for
        the temperature to reach the setpoint before raising TimeoutError with
        `asyncio.wait_for` and `wait_for_temperature` method. If `timeout` == 0,
        do not wait for the temperature to reach the setpoint (default behavior).

        ```
        if timeout == None or timeout > 0:
            await asyncio.wait_for(self.wait_for_temperature(temperature), timeout)
        ```

        Args:
            temperature (float): The temperature setpoint in degrees C.
            timeout (float, None): Time in seconds to wait before raising TimeoutError

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

    # Don't use property getter, can't use explicity with async
    # ie can't do `await temperature`
    @abstractmethod
    async def get_temperature(self):
        """Retrieves the temperature set point for the temperature controller.

        This is an abstract asynchronous method that must be implemented by
        subclasses to define how the actual temperature is read and then saved to
        `_temperature`.

        Returns:
            float: The current temperature in degrees C.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        pass

    async def wait_for_temperature(self, temperature: float, interval: float = 5.0):
        """Asynchronously wait for the temperature controller to reach the
        temperature setpoint.

        Args:
            temperature (float): The temperature setpoint in degrees C.
            interval (float): Time interval in seconds between checking temperature

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """

        while await self.get_temperature != temperature:
            await asyncio.sleep(interval)

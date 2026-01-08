from abc import ABC, abstractmethod
from typing import Union, Any
from attrs import define, field
import asyncio
import logging
from pyseq_core.utils import HW_CONFIG
from functools import cached_property

LOGGER = logging.getLogger("PySeq")


@define
class BaseCOM(ABC):
    name: str = field()
    address: str = field()
    lock: asyncio.Lock = field(factory=asyncio.Lock)
    com: Any = field(default=None, init=False)
    _cmdid: int = field(default=0)
    _connected: bool = field(default=False)

    """
    Abstract base class for communication interfaces.

    Attributes:
        name (str): Typically name of the insrument the COM is used with
        address (str): The address of the communication interface.
        config (dict): Settings for communication interface
        lock (asyncio.Lock): An asyncio lock to ensure thread-safe access to the interface.
        com (Any): Actual communication interface
    """

    @cached_property
    def config(self):
        return HW_CONFIG[self.name]["com"]

    @abstractmethod
    async def connect(self) -> Union[str, None]:
        """
        Asynchronously establishes a connection to the communication interface.

        Returns:
            str: Message if the connection is successful or already exists, otherwise None.
        """
        async with self.lock:
            self._connected = True
            pass

    @abstractmethod
    async def command(self, command: str, read: bool = True) -> Union[str, dict]:
        """
        Asynchronously sends a command to the communication interface.

        Args:
            command (str): The command string to be sent.
            read (bool): Whether to read the response from the device.
        """
        async with self.lock:
            pass

    @abstractmethod
    async def close(self) -> bool:
        """
        Asynchronously close a connection to the communication interface.

        Returns:
            bool: True if the connection is gracefully closed, otherwise False.
        """
        async with self.lock:
            pass

    def bump_cmdid(self):
        if self._cmdid >= 9999:
            self._cmdid = 0
        self._cmdid += 1
        return f"{self._cmdid:04d}"

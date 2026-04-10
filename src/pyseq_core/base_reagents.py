from __future__ import annotations
from typing import Union, Dict, TYPE_CHECKING
from attrs import define, field
from warnings import warn
from pydantic import BaseModel, model_validator
from pyseq_core.utils import HW_CONFIG
from pyseq_core.base_protocol import (
    ConfigModelFactory,
    validate_in,
    validate_min_max,
    recursive_validate,
)
import logging
from copy import deepcopy

if TYPE_CHECKING:
    from pyseq_core.base_system import BaseFlowCell


LOGGER = logging.getLogger("PySeq")


class BaseReagent(BaseModel):
    flowcell: Union[str, int]
    name: str
    port: int
    flow_rate: Union[int, float]

    """A reagent used in an experiment.

    This Pydantic model defines the fundamental properties of a reagent,
    including its associated flowcell, name, valve port, and desired flow rate.
    It includes validation to ensure the port and flow rate are within
    acceptable ranges defined in the hardware configuration (`HW_CONFIG`).

    Attributes:
        flowcell (Union[str, int]): The identifier of the flowcell this reagent
            is associated with.
        name (str): The unique name of the reagent.
        port (int): The valve port number through which this reagent is dispensed.
        flow_rate (Union[int, float]): The default flow rate for this reagent.
    """

    @model_validator(mode="after")
    def validate_port_flowrate(self):
        """Validates the reagent's port and flow rate against hardware configuration.

        Ensures that the specified `port` is a valid port for the valve
        associated with the `flowcell`, and that the `flow_rate` is within
        the minimum and maximum allowed values for the pump associated with
        the `flowcell` as defined in `HW_CONFIG`.

        It does not check if the specified `port` is already in use by another reagent.

        Raises:
            ValueError: If the port is not in the valid list for the valve,
                        or if the flow rate is outside the min/max range for the pump.

        Returns:
            BaseReagent: The validated `BaseReagent` instance.
        """
        validate_in("port", self.port, HW_CONFIG[f"Valve{self.flowcell}"])
        # validate_min_max("flow_rate", self.flow_rate, HW_CONFIG[f"Pump{self.flowcell}"])
        recursive_validate(self.model_dump(), HW_CONFIG[f"Pump{self.flowcell}"])
        return self


@define
class ReagentsManager:
    """Manages the addition, updating, and removal of reagents from flowcells.

    This class provides a centralized system for maintaining a collection of
    reagent definitions, organized by flowcell. It includes methods for validating
    reagent properties like port assignments and flow rates against the
    system's hardware configuration.

    Attributes:
        flowcells (dict): A dictionary where keys are flowcell identifiers (str or int)
            and values are objects (e.g., `Flowcell` instances) that contain a
            `reagents` attribute (which is itself a dictionary mapping reagent names
            to `BaseReagent` objects or their dictionary representations).
    """

    flowcells: Dict[Union[str, int], BaseFlowCell] = field(factory=dict)

    def reagents(self, flowcell: Union[str, int]) -> Dict[Union[str, int], BaseReagent]:
        """Retrieves the dictionary of reagents for a specific flowcell.

        Args:
            flowcell (Union[str, int]): The identifier of the flowcell.

        Returns:
            dict: A dictionary mapping reagent names (str) to `BaseReagent` objects
                (or their dictionary representations) for the specified flowcell.
        """
        return self.flowcells[flowcell].reagents

    def get_reagent_key(self, flowcell: Union[str, int], port: int) -> str:
        """Gets the reagent name (key) associated with a given port number on a flowcell.

        Args:
            flowcell (Union[str, int]): The identifier of the flowcell.
            port (int): The port number to look up.

        Returns:
            str: The name of the reagent mapped to the port, or an empty string
                if no reagent is found for that port.

        Raises:
            ValueError: If more than one reagent is mapped to the same port
                on the specified flowcell, indicating a configuration error.
        """
        reagents = self.reagents(flowcell)
        key = list(filter(lambda k: reagents[k]["port"] == port, reagents))
        if len(key) > 1:
            raise ValueError(
                f"More than 1 reagent mapped to port {port} on flowcell {flowcell}"
            )
        return "".join(key)

    def check_port(self, flowcell: Union[str, int], reagent: BaseReagent) -> bool:
        """Checks if a reagent's name or port number is already in use on a flowcell.

        This method performs two checks:
        1.  If the `reagent.name` already exists in the flowcell's reagents.
        2.  If `reagent.port` is already used by another reagent on the same flowcell.

        Args:
            flowcell (Union[str, int]): The identifier of the flowcell.
            reagent (BaseReagent): The `BaseReagent` object to check.

        Returns:
            bool: True if both the reagent name and port are available (not used),
                False otherwise.

        Warns:
            UserWarning: If the reagent name or port is found to be a duplicate.
        """

        # Check reagent name is not already listed
        reagents = self.reagents(flowcell)
        if reagent.name in reagents:
            port = reagents[reagent.name]["port"]
            warn(
                f"Duplicate Port: {reagent.name} already mapped to port {port} on flowcell {flowcell}",
                UserWarning,
            )
            return False

        # Check port not used by another reagent
        existing_reagent = self.get_reagent_key(flowcell, reagent.port)
        if len(existing_reagent) > 0:
            warn(
                f"Duplicate Port: Port {reagent.port} is already used by {existing_reagent} on flowcell {flowcell}",
                UserWarning,
            )
            return False

        return True

    def check_flow_rate(
        self, flowcell: Union[str, int], flow_rate: Union[int, float]
    ) -> bool:
        """Checks if a given flow rate is within the valid range for the pump on a flowcell.

        This method uses `validate_min_max` to ensure the `flow_rate` adheres
        to the hardware configuration limits for the pump associated with the
        specified `flowcell`.

        Args:
            flowcell (Union[str, int]): The identifier of the flowcell.
            flow_rate (Union[int, float]): The flow rate to validate.

        Returns:
            bool: True if the flow rate is valid.

        Raises:
            ValueError: If the flow rate is outside the min/max range defined
                in `HW_CONFIG` for the corresponding pump.
        """
        # Validate flow rates
        validate_min_max("flow_rate", flow_rate, HW_CONFIG[f"Pump{flowcell}"])
        return True

    def add(
        self, reagent: Union[BaseReagent, None] = None, **kwargs
    ) -> Dict[Union[str, int], BaseReagent]:
        """Adds a reagent to a specific flowcell.

        If a `reagent` object is provided, it is added directly after validation.
        Otherwise, a new `BaseReagent` object is created from `kwargs` and then added.
        The reagent is only added if its name and port are not already in use.

        Args:
            reagent (BaseReagent, optional): An existing `BaseReagent` object to add.
                If None, a new reagent will be created using `kwargs`. Defaults to None.
            **kwargs: Keyword arguments used to create a new `BaseReagent` if `reagent`
                is None. These are passed directly to the `BaseReagent` constructor.

        Returns:
            dict: The updated dictionary of reagents for the target flowcell.
        """

        if reagent is None:
            reagent = BaseReagent(**kwargs)

        flowcell = reagent.flowcell
        # Add reagent if both port and reagent name are not already used
        if self.check_port(flowcell, reagent):
            LOGGER.info(f"Added reagent {reagent.name}")
            LOGGER.debug(f"{reagent}")
            self.reagents(flowcell)[reagent.name] = reagent.model_dump()

        return self.reagents(flowcell)

    def update(
        self, reagent: BaseReagent = None, **kwargs
    ) -> Dict[Union[str, int], BaseReagent]:
        """Updates an existing reagent's parameters on a flowcell.

        This method allows for updating a reagent identified either by an
        existing `BaseReagent` object or by its name/port via `kwargs`.
        It handles changes to reagent name, port, flow rate, and other
        custom parameters, performing validation where applicable.

        Args:
            reagent (BaseReagent, optional): An existing `BaseReagent` object
                with updated parameters. If None, the reagent to update is
                identified and updated using `kwargs`. Defaults to None.
            **kwargs: Keyword arguments containing the `flowcell`, `name` (required
                if `reagent` is None), and optionally `port` (if identifying by port)
                and other parameters to update.

        Returns:
            dict: The updated dictionary of reagents for the target flowcell.

        Raises:
            AssertionError: If `name` and `flowcell` are not specified in `kwargs`
                            when `reagent` is None.
            ValueError: If no existing reagent is found with the specified name or port,
                        or if a new port conflicts with existing mappings.
            UserWarning: If a duplicate reagent name or port conflict occurs during update.
        """

        if reagent is None:
            assert "name" in kwargs, "name must be specified"
            assert "flowcell" in kwargs, "flowcell must be specified"
            flowcell = kwargs["flowcell"]
            if kwargs["name"] in self.flowcells[flowcell].reagents:
                reagent = self.flowcells[flowcell].reagents[kwargs["name"]].copy()
                reagent.update(**kwargs)
            elif "port" in kwargs:
                old_name = self.get_reagent_key(flowcell, kwargs["port"])
                if len(old_name) > 0:
                    reagent = self.flowcells[flowcell].reagents[old_name].copy()
                    reagent.update(**kwargs)
                else:
                    ValueError(f"No existing reagent with port {kwargs['port']}")
            else:
                raise ValueError(f"Invalid reagent name {kwargs['name']}")

        if isinstance(reagent, BaseReagent):
            reagent = reagent.model_dump()

        flowcell = reagent["flowcell"]
        reagents = self.reagents(flowcell)
        reagent_name = self.get_reagent_key(flowcell, reagent["port"])
        if len(reagent_name) == 0:
            reagent_name = reagent["name"]

        # Update reagent name
        if reagent_name != reagent["name"]:
            filter_names = [k for k in reagents.keys() if k != reagent_name]
            if reagent["name"] not in filter_names:
                # new name does not match existing reagent
                reagent_values = reagents.pop(reagent_name)  # remove old name
                reagent_values["name"] = reagent["name"]  # update to new name
                reagents[reagent["name"]] = reagent_values  # add reagent with new name
                reagent_name = reagent["name"]
            else:
                # new name matches existing reagent
                port = reagents[reagent["name"]]
                warn(
                    f"Duplicate Port: {reagent['name']} already mapped to port {port} on flowcell {flowcell}",
                    UserWarning,
                )

        # Update port
        if reagents[reagent_name]["port"] != reagent["port"]:
            # validate port
            validate_in("port", reagent["port"], HW_CONFIG[f"Valve{flowcell}"])
            # check if port used by another reagent
            existing_reagent = self.get_reagent_key(flowcell, reagent["port"])
            if len(existing_reagent) == 0:  # or existing_reagent == reagent['name']:
                reagents[reagent_name].update({"port": reagent["port"]})  # update port

        # Update flowrate
        if reagents[reagent_name]["flow_rate"] != reagent["flow_rate"]:
            if self.check_flow_rate(flowcell, reagent["flow_rate"]):
                reagents[reagent_name].update({"flow_rate": reagent["flow_rate"]})

        # Update other parameter, no check though
        del reagent["port"]
        del reagent["flow_rate"]
        del reagent["name"]
        del reagent["flowcell"]
        reagents[reagent_name].update(reagent)

        return reagents

    def remove(
        self, flowcell: Union[str, int], reagent_name: str
    ) -> Dict[Union[str, int], BaseReagent]:
        """Removes a reagent from a specific flowcell.

        Args:
            flowcell (Union[str, int]): The identifier of the flowcell from which
                to remove the reagent.
            reagent_name (str): The name of the reagent to remove.

        Returns:
            dict: The updated dictionary of reagents for the target flowcell
                after removal.
        """
        reagents = self.reagents(flowcell)

        if reagent_name in reagents:
            del reagents[reagent_name]

        return reagents

    def add_from_config(self, flowcell: Union[str, int], config: dict):
        """Adds reagents to a flowcell based on a configuration dictionary.

        This method reads reagent definitions from a provided configuration,
        dynamically creates `Reagent` objects (potentially with extra pump
        parameters), and adds them to the manager. It supports different
        formats for reagent definitions within the config.

        Args:
            flowcell (Union[str, int]): The identifier of the flowcell to which
                reagents will be added.
            config (dict): A dictionary containing reagent definitions.
                Expected structure:
                `config["pump"]` for extra pump parameters.
                `config["reagents"]` for reagent definitions.
                Reagent definitions can be:
                - `reagent_name: port_number` (int)
                - `reagent_name: {port: port_number, flow_rate: flow_rate, ...}` (dict)
        """

        ExpConfigFactory = ConfigModelFactory(config)
        Reagent = ExpConfigFactory.get_model("pump", BaseReagent)

        reagent_config = deepcopy(config.get("reagents", {}))

        for name, params in reagent_config.items():
            if isinstance(params, int):
                # reagent_name: port number
                params = {"flowcell": flowcell, "name": name, "port": params}
            elif isinstance(params, dict):
                # reagent_name: {port: port_number, flow_rate: flow_rate, ...}
                params.update({"name": name, "flowcell": flowcell})
            reagent = Reagent(**params)
            self.add(reagent)

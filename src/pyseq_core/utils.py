from pathlib import Path
import tomlkit
import yaml
import os
import shutil
from importlib import resources
import logging
import logging.config  # Need to import, or I get an AttributeError?
import datetime
import re
import inspect
from typing import Union, TypeVar, Type, List, TYPE_CHECKING

if TYPE_CHECKING:
    from pyseq_core.base_com import BaseCOM


LOGGER = logging.getLogger("PySeq")
"""Logger instance for the PySeq application."""

# --- MACHINE_SETTINGS Configuration ---
# This section handles the loading of machine-specific hardware configurations.


# Use resource file from a different "pyseq" package
def get_sequencer_package_path(caller_frame: List[inspect.FrameInfo]) -> Path:
    """Get the path to the sequencer specific pyseq package being used.

    Returns:
        Path to the sequencer specific pyseq package.
    """

    pattern = re.compile(r"(pyseq[\w|-|_]+)", re.IGNORECASE)
    for frame in caller_frame:
        match = re.findall(pattern, frame.filename)
        if match:
            for m in match:
                package = m.lower()
                if package != "pyseq_core":
                    try:
                        return resources.files(package)
                    except ModuleNotFoundError:
                        # pyseq is in filepath, ignore
                        pass


if os.environ.get("PYTEST_VERSION") is not None:
    RESOURCE_PATH = get_sequencer_package_path(inspect.stack())
    if RESOURCE_PATH is None:
        # Fallback to pyseq_core resources in remote tests
        RESOURCE_PATH = resources.files("pyseq_core")
    # for frame in caller_frame:
    #     match = re.findall(pattern, frame.filename)
    #     if match:
    #        for m in match:
    #            package = m.lower()
    #            if package != "pyseq_core":
    #                try:
    #                     RESOURCE_PATH = resources.files(package)
    #                     break
    #                except ModuleNotFoundError:
    #                    # pyseq is in filepath, ignore
    #                    pass


MACHINE_SETTINGS_PATH = Path.home() / ".config/pyseq/machine_settings.yaml"
MACHINE_SETTINGS_RESOURCE = RESOURCE_PATH.joinpath("resources/machine_settings.yaml")
"""Path to the machine-specific hardware configuration YAML file.

This YAML file stores hardware configurations and settings for all the
instrumentation in the sequencer. Multiple sequencers or versions can be
stored in one file. The top-level key `name` specifies which sequencer or
version to use, and its corresponding settings are loaded into `HW_CONFIG`.

If the file does not exist at `~/.config/pyseq/machine_settings.yaml`,
settings from the `pyseq_core` package resources will be copied and used as a fallback.
"""

if not MACHINE_SETTINGS_PATH.exists():
    # Copy settings from package if local machine setting do not exist
    os.makedirs(MACHINE_SETTINGS_PATH.parent, exist_ok=True)
    os.makedirs(MACHINE_SETTINGS_PATH.parent / "logs", exist_ok=True)
    resource_path = resources.files("pyseq_core")
    shutil.copy(MACHINE_SETTINGS_RESOURCE, MACHINE_SETTINGS_PATH)

with open(MACHINE_SETTINGS_PATH, "r") as f:
    all_settings = yaml.safe_load(f)  # Machine config
    machine_name = all_settings["name"]
    HW_CONFIG = all_settings[machine_name]
"""Dictionary containing the hardware configuration for the currently selected machine.

This is loaded from the `MACHINE_SETTINGS_PATH` YAML file, specifically the
section identified by the `name` key in that file.
"""

# --- DEFAULT_CONFIG Configuration ---
# This section handles the loading of default experiment/software configurations.
DEFAULT_CONFIG_PATH = Path.home() / ".config/pyseq/default.toml"
DEFAULT_CONFIG_RESOURCE = RESOURCE_PATH.joinpath("resources/default.toml")
"""Path to the default experiment configuration TOML file.

If `PYTEST_VERSION` environment variable is set and the machine name
contains "test" or "virtual", the default configuration from the `pyseq_core`
package resources is used. Otherwise, it defaults to `~/.config/pyseq/default.toml`.
"""

if not DEFAULT_CONFIG_PATH.exists():
    # Copy settings from package if local machine setting do not exist
    resource_path = resources.files("pyseq_core")
    shutil.copy(DEFAULT_CONFIG_RESOURCE, DEFAULT_CONFIG_PATH)

# Default settings for experiment/software
machine_name = machine_name.lower()
if os.environ.get("PYTEST_VERSION") is not None and ("test" in machine_name):
    # use default experiment config and machine settings from package resources
    LOGGER.info("Using package default.toml")
    DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_RESOURCE
    # override HW_CONFIG with package resource
    with open(MACHINE_SETTINGS_RESOURCE, "r") as f:
        LOGGER.info("Using package machine_settings.yaml")
        all_settings = yaml.safe_load(f)  # Machine config
        machine_name = all_settings["name"]
        HW_CONFIG = all_settings[machine_name]

# Read default config and machine settings
DEFAULT_CONFIG = tomlkit.parse(open(DEFAULT_CONFIG_PATH).read())
"""Dictionary containing the default experiment and software configuration.

This is loaded from the `DEFAULT_CONFIG_PATH` TOML file.
"""


def deep_merge(src_dict: dict, dst_dict: dict) -> dict:
    """Recursively merges a source dictionary into a destination dictionary.

    If a key exists in both dictionaries and both values are dictionaries,
    the merge operation is performed recursively on those nested dictionaries.
    Otherwise, the value from the source dictionary overwrites the value
    in the destination dictionary.

    Args:
        src_dict (dict): The source dictionary whose contents will be merged.
        dst_dict (dict): The destination dictionary into which `src_dict` will be merged.

    Returns:
        dict: The modified destination dictionary after the merge operation.
    """

    for k, v in src_dict.items():
        if k in dst_dict and isinstance(dst_dict[k], dict) and isinstance(v, dict):
            deep_merge(src_dict[k], dst_dict[k])
        else:
            dst_dict[k] = v

    return dst_dict


def setup_experiment_path(exp_config: dict, exp_name: str) -> dict:
    """Sets up and creates output paths for experiment data.

    This function configures paths for images, focus data, and logs based on
    the provided experiment configuration and name. It ensures that the
    necessary directories are created and updates the `exp_config` dictionary
    with the absolute paths. It also updates the logger's file handler filename.

    Args:
        exp_config (dict): The experiment configuration dictionary.
            Expected to contain an "experiment" key with "name", "output_path",
            "images_path", "focus_path", and "log_path" subkeys.
            Also expects a "logging" key with "handlers" and "fileHandler" subkeys.
        exp_name (str): The desired name for the experiment. If empty, the name
            from `exp_config["experiment"]["name"]` is used. If that is also empty,
            a default name based on the current date is generated.

    Returns:
        dict: The updated experiment configuration dictionary with resolved paths.
    """

    # Get experiment name
    if len(exp_name) == 0:
        exp_name = exp_config["experiment"]["name"]
    if len(exp_name) == 0:
        exp_name = "PySeq_" + datetime.datetime.now().strftime("%Y%m%d")
    exp_config["experiment"]["name"] = exp_name
    # Setup paths output paths for images, logs, and focus data
    output_path = Path(exp_config["experiment"]["output_path"]) / exp_name
    paths = ["images", "focus", "log"]
    for p in paths:
        config_path = exp_config["experiment"][f"{p}_path"]
        if len(config_path) == 0:
            p_ = output_path / p
        else:
            p_ = Path(config_path) / exp_name / p
        p_.mkdir(parents=True, exist_ok=True)
        exp_config["experiment"][f"{p}_path"] = str(p_)

    # Update logger configuration
    exp_config["logging"]["handlers"]["fileHandler"]["filename"] = (
        f"{p_}/{exp_name}.log"
    )
    return exp_config


def update_logger(logger_conf: dict, rotating: bool = False):
    """Updates the logging configuration based on the `rotating` flag.

    This function modifies the provided logger configuration dictionary.
    If `rotating` is True, it configures a `RotatingFileHandler` and removes
    the standard `FileHandler`. If `rotating` is False, it removes the
    `RotatingFileHandler` and assumes a standard `FileHandler` is used.
    Finally, it applies the updated configuration using `logging.config.dictConfig`.

    Args:
        logger_conf (dict): The logging configuration dictionary, typically
            loaded from a configuration file.
        rotating (bool, optional): If True, configures a rotating file handler.
            If False, configures a standard file handler. Defaults to False.
    """
    if rotating:
        # Remove FileHandler if running tests or idleing
        del logger_conf["handlers"]["fileHandler"]
        filename = logger_conf["handlers"]["rotatingHandler"]["filename"]
        filename = Path(filename).expanduser()

        logger_conf["handlers"]["rotatingHandler"]["filename"] = str(filename)
    else:
        # Remove RotatingFileHandler during experiment runs
        del logger_conf["handlers"]["rotatingHandler"]

    logger_conf["loggers"]["PySeq"]["handlers"] = list(logger_conf["handlers"].keys())

    if not os.environ.get("PYTEST_VERSION"):
        # Need to import logging.config or get an AttributeError, not sure why.
        logging.config.dictConfig(logger_conf)
    else:
        # Add file handler to logger to use caplog in pytest
        # Tried passing disable_existing_loggers = False to dictConfig,
        # But caplog still gets over written
        logger = logging.getLogger("PySeq")
        fname = logger_conf["handlers"]["fileHandler"]["filename"]
        fmt_ = logger_conf["formatters"]["long"]
        fmt = logging.Formatter(fmt=fmt_["format"], datefmt=fmt_["datefmt"])
        handler = logging.FileHandler(filename=fname)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(fmt)
        logger.addHandler(handler)


def map_coms(
    com_class: "BaseCOM", address_dict: dict = None, hw_config: dict = HW_CONFIG
):
    """Maps instrument names to their communication instances.

    This function iterates through the `HW_CONFIG` to identify instruments
    that have a COM identifiers. It then creates or reuses instances of `com_class`
    for these identifiers, ensuring that multiple instruments sharing the same
    physical communication address (e.g., a serial port) share the same
    communication object.

    Args:
        com_class (BaseCOM): The class to instantiate for communication objects.
            This class is expected to be a concrete implementation of `BaseCOM`
            and take an address as its constructor argument.
        address_dict: Dictionary with identifiers as key and communications addresses as values

    Returns:
        dict: A dictionary where keys are instrument names (or communication addresses
            if an instrument shares an address) and values are instances of `com_class`.
    """
    _coms = {}
    for instrument, values in hw_config.items():
        if "com" in values:
            _coms[instrument] = values["com"]["address"]

    coms = {}
    for instrument, com_id in _coms.items():
        if address_dict is None:
            # Identifier is the actual address
            address = com_id
        else:
            # Get actual address from identifier
            address = address_dict.get(com_id, None)

        if com_id in coms:
            # If the address already has a COM object, assign it to this instrument
            coms[instrument] = coms[com_id]
            LOGGER.debug(
                f"{instrument} using shared coms at {coms[instrument].address}"
            )
        elif com_id in _coms:
            # If the address is also an instrument name (e.g., 'Instrument1': {'address': 'Instrument1'}),
            # create a new COM object for the address and assign it to both.
            coms[com_id] = com_class(name=instrument, address=address)
            LOGGER.debug(f"{com_id} using shared coms at {coms[com_id].address}")
            if instrument not in coms:
                coms[instrument] = coms[com_id]
                LOGGER.debug(
                    f"{instrument} using shared coms at {coms[instrument].address}"
                )
        elif instrument in coms:
            LOGGER.debug(f"{instrument} already assigned to {coms[instrument].address}")
            # If the instrument already has a COM object (e.g., from a previous alias), do nothing
        elif com_id not in coms:
            LOGGER.error(f"Could not find coms with id {com_id} for {instrument}")
            coms[instrument] = com_class(name=instrument, address=address)
        else:
            # If neither the address nor the instrument is already mapped, create a new COM object
            coms[instrument] = com_class(name=instrument, address=address)
            LOGGER.debug(f"{instrument} using coms at {coms[instrument].address}")

    return coms


T = TypeVar("T", bound=object)


def parse(
    pattern: re.Pattern, string: str, attributes: Type[T] = None
) -> Union[T, tuple]:
    match = re.search(pattern, string)
    if match and attributes is not None:
        return attributes(*match.groups())
    elif match:
        return match.groups()
    elif not match:
        raise ValueError(f"Could not parse {pattern} with {string}")

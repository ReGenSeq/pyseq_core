from pydantic import (
    BaseModel,
    create_model,
    computed_field,
    PositiveInt,
    PositiveFloat,
    NonNegativeFloat,
    NonNegativeInt,
    field_validator,
    model_validator,
    Field,
    ConfigDict,
)
from pyseq_core.utils import DEFAULT_CONFIG, HW_CONFIG, deep_merge
from functools import cached_property, lru_cache
from typing import Union, Any, Type, Tuple
from math import ceil, copysign
from warnings import warn
import yaml
import logging
import tomlkit
from typing_extensions import Self
from copy import deepcopy
from os import getcwd
from enum import Enum
from pathlib import Path


# Set up logging
LOGGER = logging.getLogger("PySeq")


def custom_params(config: dict) -> dict:
    """Get type and default value pairs for pydantic BaseModel fields from config.

    Use with pydantic.create_model
    """
    kwargs = {}
    for k, v in config.items():
        # Handle TOML unwrapped values
        value = v.unwrap() if hasattr(v, "unwrap") else v
        kwargs[k] = (type(value), value)
    return kwargs


class ConfigModelFactory:
    def __init__(self, exp_config: dict):
        """Factory fo creating dynamic command models from TOML config.

        Initialize for each experiment.
        """
        self.exp_config = exp_config

    def get_model(
        self, section_key: str, base_model: Type[BaseModel]
    ) -> Type[BaseModel]:
        """
        Returns a Pydantic model for a TOML section,
        validated against a specific hardware entry.
        """
        # get the releveant section of the experiment config
        section_data = self.exp_config.get(section_key, {})

        # freeze config for lru_cache
        frozen_config = self._freeze_dict(section_data)

        # retrieve or create the class from the global cache
        return self._get_cached_model(section_key, frozen_config, base_model)

    @staticmethod
    @lru_cache(maxsize=256)
    def _get_cached_model(
        section_key: str,
        frozen_config: Tuple,
        base_model: Type[BaseModel],
    ) -> Type[BaseModel]:
        config_dict = ConfigModelFactory._unfreeze_dict(frozen_config)

        # generate dynamic nested model
        return ConfigModelFactory._nested_model(
            section_key.capitalize(), config_dict, base_model
        )

        # NewModel = create_model(
        #             f"{section_key}_model",
        #             __base__ = base_model,
        #             **fields # type: ignore
        # )
        # return NewModel

    @staticmethod
    def _nested_model(
        model_name: str, config: Any, base_model: Union[None, Type[BaseModel]] = None
    ) -> Any:
        """Recursively build nest pydantic model."""
        kwargs = {}

        if isinstance(config, dict):
            for k, v in config.items():
                # tomlkit specific: unwrap objects to raw Python types
                value = v.unwrap() if hasattr(v, "unwrap") else v
                if isinstance(value, dict):
                    _model_name = f"{model_name}_{k.capitalize()}"
                    _model = ConfigModelFactory._nested_model(_model_name, value)
                    kwargs[k] = (_model, _model())
                else:
                    kwargs[k] = (type(value), value)

        if base_model is None:
            return create_model(model_name, **kwargs)
        else:
            return create_model(model_name, __base__=base_model, **kwargs)

    @staticmethod
    def _freeze_dict(data: Any) -> Any:
        """
        Recursively converts tomlkit/dicts/lists into hashable tuples.
        Also handles the .unwrap() during the freezing process.
        """
        # Unwrap tomlkit objects immediately so the cache key is 'clean'
        val = data.unwrap() if hasattr(data, "unwrap") else data

        if isinstance(val, dict):
            return tuple(
                (k, ConfigModelFactory._freeze_dict(v)) for k, v in sorted(val.items())
            )
        elif isinstance(val, (list, tuple)):
            return tuple(ConfigModelFactory._freeze_dict(i) for i in val)
        # elif isinstance(val, (int, str)):
        #     return tuple(ConfigModelFactory._freeze_dict(i) for i in val)
        return val

    @staticmethod
    def _unfreeze_dict(data) -> Any:
        """
        Recursively converts hashable tuples into dictionaries.
        """
        if isinstance(data, tuple):
            # Check if it looks like ((key, value), (key, value))
            if all(isinstance(i, tuple) and len(i) == 2 for i in data):
                return {k: ConfigModelFactory._unfreeze_dict(v) for k, v in data}
        return data


DefaultModelFactory = ConfigModelFactory(DEFAULT_CONFIG)


def recursive_validate(query_dict, valid_dict):
    """Recursively validate fields in query dictionary.

    The query dictionary is validated againt a valid dictionary from a config file.
    Data can be validated between min/max values if min_val and max_val keys are in the config file.
    Or data can be validate to be in a list if a valid_list key is in the config file.

    """

    for k, v in query_dict.items():
        if k in valid_dict:
            if isinstance(v, dict) and isinstance(valid_dict[k], dict):
                recursive_validate(v, valid_dict[k])
            elif "max_val" in valid_dict[k] and "min_val" in valid_dict[k]:
                validate_min_max(k, v, valid_dict)
            elif "valid_list" in valid_dict:
                validate_in(k, v, valid_dict)


def validate_min_max(
    parameter: str, value: Union[int, float], valid_dict=HW_CONFIG
) -> Union[int, float]:
    """Validate value to be between min/max values for a specific instrument.

    The valid_dict should have the structure:
    {parameter: {min_val: some_min_value,
                 max_val: some_max_value}

    """

    min_val = valid_dict[parameter]["min_val"]
    max_val = valid_dict[parameter]["max_val"]
    units = valid_dict[parameter].get("units", "")

    if min_val <= value <= max_val:
        return value
    else:
        msg = f"{parameter} value ({value}) should be between {min_val} and {max_val} {units}"
        LOGGER.error(msg)
        raise ValueError(msg)


def validate_in(parameter: Any, value: Any, valid_dict: dict) -> Any:
    """Validate value to be in a valid list."""
    if value in valid_dict[parameter]["valid_list"]:
        return value
    else:
        msg = f"{parameter} value ({value}) not in valid list"
        LOGGER.error(msg)
        raise ValueError(msg)


FLOWCELLS = Enum("FLOWCELLS", {f.upper(): f for f in HW_CONFIG["flowcells"]})


class BaseStagePosition(BaseModel):
    """Stage position information to tile over a region of interest."""

    model_config = ConfigDict(use_enum_values=True)
    flowcell: FLOWCELLS
    x_init: Union[int, float]
    x_last: Union[int, float]
    y_init: Union[int, float]
    y_last: Union[int, float]
    z_init: Union[int, float, None] = None
    nz: int = 1  # Updated by experiment config NOT protocol
    # Not a cached_property because want to change easily
    z_step: PositiveInt = HW_CONFIG.get("ZStage").get("step")
    overlap: NonNegativeFloat = 0.0  # in microns

    @computed_field
    @property
    def x(self) -> Union[int, float]:
        return self.x_init

    @computed_field
    @property
    def y(self) -> Union[int, float]:
        return self.y_init

    @computed_field
    @property
    def z(self) -> Union[int, float]:
        return self.z_init if self.z_init is not None else 0

    @computed_field
    @cached_property
    def x_step(self) -> Union[int, float]:
        return HW_CONFIG["XStage"]["step"]

    @computed_field
    @cached_property
    def y_step(self) -> Union[int, float]:
        return HW_CONFIG["YStage"]["step"]

    @cached_property
    def x_spum(self) -> float:
        return HW_CONFIG["XStage"]["spum"]

    @cached_property
    def y_spum(self) -> float:
        return HW_CONFIG["YStage"]["spum"]

    @cached_property
    def z_spum(self) -> float:
        return HW_CONFIG["ZStage"]["spum"]

    @computed_field
    @property
    def nx(self) -> PositiveInt:
        nx = abs(self.x_last - self.x_init) / (self.x_step - self.overlap * self.x_spum)
        return ceil(nx)

    @computed_field
    @property
    def ny(self) -> PositiveInt:
        ny = abs(self.y_last - self.y_init) / (self.y_step - self.overlap * self.y_spum)
        return ceil(ny)

    @computed_field
    @property
    def x_middle(self) -> Union[int, float]:
        return int((self.x_last - self.x_init) / 2 + self.x_init)

    @computed_field
    @property
    def y_middle(self) -> Union[int, float]:
        return int((self.y_last - self.y_init) / 2 + self.y_init)

    @computed_field
    @property
    def z_middle(self) -> Union[int, float]:
        z_init = self.z_init if self.z_init is not None else 0
        z_last = self.z_last if self.z_last is not None else 0
        return int((z_last - z_init) / 2 + z_init)

    @computed_field
    @property
    def z_last(self) -> Union[int, float]:
        z_init = self.z_init if self.z_init is not None else 0
        return z_init + self.z_step * self.nz

    @computed_field
    @property
    def x_direction(self) -> int:
        return int(copysign(1, self.x_last - self.x_init))

    @computed_field
    @property
    def y_direction(self) -> int:
        return int(copysign(1, self.y_last - self.y_init))

    @computed_field
    @property
    def z_direction(self) -> int:
        z_init = self.z_init if self.z_init is not None else 0
        z_last = self.z_last if self.z_last is not None else 0
        return int(copysign(1, z_last - z_init))

    @field_validator("x_init", "x_last", mode="after")
    @classmethod
    def validate_x_pos(cls, value: Union[int, float]) -> Union[int, float]:
        return validate_min_max("position", value, HW_CONFIG.get("XStage", {}))

    @field_validator("y_init", "y_last", mode="after")
    @classmethod
    def validate_y_pos(cls, value: Union[int, float]) -> Union[int, float]:
        return validate_min_max("position", value, HW_CONFIG.get("YStage", {}))

    @field_validator("z_init", mode="after")
    @classmethod
    def validate_z_pos(cls, value: Union[int, float]) -> Union[int, float]:
        if value is not None:
            return validate_min_max("position", value, HW_CONFIG.get("ZStage", {}))
        return value

    @model_validator(mode="after")
    def validate_stage_positions(self) -> Self:
        z_init = self.z_init if self.z_init is not None else 0
        z_last = z_init + self.z_step * self.nz
        validate_min_max("position", z_last, HW_CONFIG.get("ZStage", {}))
        return self


StagePosition = DefaultModelFactory.get_model("stage", BaseStagePosition)
StagePositionType = Type[StagePosition]


class BaseSimpleStage(BaseModel):
    """Simple x,y,z coordinates."""

    x: Union[int, float]
    y: Union[int, float]
    z: Union[int, float]

    @field_validator("x", mode="after")
    @classmethod
    def validate_x_pos(cls, value: int) -> int:
        return validate_min_max("position", value, HW_CONFIG["XStage"])

    @field_validator("y", mode="after")
    @classmethod
    def validate_y_pos(cls, value: int) -> int:
        return validate_min_max("position", value, HW_CONFIG["YStage"])

    @field_validator("z", mode="after")
    @classmethod
    def validate_z_pos(cls, value: int) -> int:
        return validate_min_max("position", value, HW_CONFIG["ZStage"])


SimpleStagePosition = DefaultModelFactory.get_model("stage", BaseSimpleStage)
SimpleStageType = Type[SimpleStagePosition]


class CustomROI(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    flowcell: FLOWCELLS
    overlap: NonNegativeInt  # in pixels


CUSTOM_ROI = ConfigModelFactory._nested_model(
    "CustomROI", DEFAULT_CONFIG["roi_fields"], CustomROI
)
# CUSTOM_ROI = create_model("CustomROI", __base__ = CustomROI, **roi_fields)


OpticsParams = DefaultModelFactory.get_model("optics", BaseModel)
OpticsParamsType = Type[OpticsParams]


class BaseImageParams(BaseModel):
    optics: OpticsParams
    image_dir: Path = getcwd()
    nz: PositiveInt
    overlap: PositiveInt


ImageParams = DefaultModelFactory.get_model("image", BaseImageParams)
ImageParamsType = Type[ImageParams]


af_routines = {
    "".join(r.upper().split()): r
    for r in DEFAULT_CONFIG["auto_focus_routines"]["routines"]
}
AF_ROUTINES = Enum("AF_ROUTINES", af_routines)


class BaseFocusParams(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    optics: OpticsParamsType = OpticsParams()
    routine: AF_ROUTINES
    output: Path = getcwd()
    tolerance: float  # for RANSAC fitting, distance in microns, ~ size diameter of cell
    coverage: float  # Fraction of tile that should be covered during focusing
    # object_diameter: Union[int, float] # size of objects in um, ie cell diameter
    # edge_threshold: float # percent of fov possibly taken up by an edge
    z_focus: Union[int, float, None] = None


FocusParams = DefaultModelFactory.get_model("focus", BaseFocusParams)
FocusParamsType = Type[FocusParams]


class BaseExposeParams(BaseModel):
    optics: OpticsParamsType = OpticsParams()


ExposeParams = DefaultModelFactory.get_model("expose", BaseExposeParams)
ExposeParamsType = Type[ExposeParams]


class ROIname(BaseModel):
    name: str

    @model_validator(mode="before")
    @classmethod
    def fill_defaults_from_annotations(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Identify which fields we want to auto-fill
        target_fields = ["image", "focus", "expose"]

        for field_name in target_fields:
            # Dynamically get the class type from the field annotation
            field_info = cls.model_fields.get(field_name)
            if not field_info:
                continue
            model_class = field_info.annotation

            # Get the specific ROI overrides (or empty dict if missing)
            roi_overrides = data.get(field_name, {})

            try:
                # Get factory-produced defaults
                default_data = model_class().model_dump()

                # Deep merge overrides into the defaults
                data[field_name] = deep_merge(roi_overrides, default_data)

            except Exception as e:
                LOGGER.error(e)

        return data


class BaseROI(BaseModel):
    name: str
    stage: StagePosition
    image: ImageParams = Field(default_factory=ImageParams)
    focus: FocusParams = Field(default_factory=FocusParams)
    expose: ExposeParams = Field(default_factory=ExposeParams)


class ValveCommand(BaseModel):
    """Validated command to select a port on a valve."""

    port: int
    flowcell: Union[str, int, None] = None

    @model_validator(mode="after")
    def validate_port(self) -> Self:
        validate_in("port", self.port, HW_CONFIG[f"Valve{self.flowcell}"])
        return self


class TemperatureCommand(BaseModel):
    """Validated command to set the flowcell temperature."""

    temperature: float
    timeout: NonNegativeFloat | None = 0
    flowcell: Union[str, int, None] = None

    @model_validator(mode="after")
    def validate_temperature(self) -> Self:
        validate_min_max(
            "temperature",
            self.temperature,
            HW_CONFIG[f"TemperatureController{self.flowcell}"],
        )
        return self


class HoldCommand(BaseModel):
    """Command to hold/incubate flowcell for specied duration (s)."""

    duration: PositiveFloat
    flowcell: Union[str, int, None] = None


class WaitCommand(BaseModel):
    """Command to pause flowcell until the microscope to available."""

    event: str = "microscope"
    flowcell: Union[str, int, None] = None


class UserCommand(BaseModel):
    """Command to pause flowcell until a user confirms a message."""

    message: str
    timeout: Union[PositiveFloat, None] = None
    flowcell: Union[str, int, None] = None


class BasePumpCommand(BaseModel):
    """Partially validated command to pump a reagent. '

    Volume in uL and flow rate in uL/min are validated.
    Reagent is not validated.
    """

    volume: PositiveFloat
    flow_rate: NonNegativeFloat
    reagent: Union[int, str, None] = None
    flowcell: Union[str, int, None] = None

    @model_validator(mode="after")
    def validate_flowrate_volume(self) -> Self:
        if self.flow_rate is not None and self.flow_rate != 0:
            validate_min_max(
                "flow_rate", self.flow_rate, HW_CONFIG.get(f"Pump{self.flowcell}", {})
            )
        validate_min_max(
            "volume", self.volume, HW_CONFIG.get(f"Pump{self.flowcell}", {})
        )
        if isinstance(self.reagent, int):
            validate_in(
                "port", self.reagent, HW_CONFIG.get(f"Valve{self.flowcell}", {})
            )
        return self


PumpCommand = DefaultModelFactory.get_model("pump", BasePumpCommand)
PumpCommandType = Type[PumpCommand]


def simple_txt_to_yaml(file_path: str) -> dict:
    modified_yaml = ""
    with open(file_path, "r") as file:
        for line in file:
            stripped_line = line.strip()
            if stripped_line:
                if ":" not in stripped_line:
                    stripped_line = f"{stripped_line}:"
                modified_yaml += f"- {stripped_line}\n"
    return yaml.safe_load(modified_yaml)


def read_protocol(file_path: str) -> dict:
    """Read a protocol from a YAML file."""

    protocols = dict()
    with open(file_path, "r") as file:
        yaml_stream = yaml.safe_load_all(file)
        for i, doc in enumerate(yaml_stream):
            name = doc.get("name", f"Protocol {i + 1}")
            cycles = doc.get("cycles", 1)
            if "steps" not in doc:
                _steps = simple_txt_to_yaml(file_path)
            else:
                _steps = doc.get("steps")
            steps = list()
            for s in _steps:
                for command, params in s.items():
                    steps.append((command, params))

            protocols[name] = {"name": name, "cycles": cycles, "steps": steps}
    return protocols


def check_hold(flowcell: str, params: Union[dict, int]) -> dict:
    if isinstance(params, dict):
        command = HoldCommand(flowcell=flowcell, **params)
    else:
        command = HoldCommand(flowcell=flowcell, duration=params)
    return command.model_dump()


# Only allow waiting for microscope, no other event waiting set up
def check_wait(flowcell: str, params: Union[dict, int]) -> dict:
    if isinstance(params, dict):
        if "event" in params and params["event"] != "microscope":
            LOGGER.warning("Only able to wait for microscope")
            warn("Only able to wait for microscope", UserWarning)
        params["event"] = "microscope"
        command = WaitCommand(flowcell=flowcell, **params)
    else:
        if params != "microscope":
            LOGGER.warning("Only able to wait for microscope")
            warn("Only able to wait for microscope", UserWarning)
        command = WaitCommand(flowcell=flowcell, event="microscope")
    return command.model_dump()


def check_user(flowcell: str, params: Union[dict, str]) -> dict:
    if isinstance(params, dict):
        command = UserCommand(flowcell=flowcell, **params)
    else:
        command = UserCommand(flowcell=flowcell, message=params)
    return command.model_dump()


def check_valve(flowcell: str, params: Union[dict, int]) -> dict:
    """Format and check valve commands.

    VALVE: {reagent: str|int}

    """

    if isinstance(params, dict):
        command = ValveCommand(flowcell=flowcell, **params)
    elif isinstance(params, int):
        command = ValveCommand(flowcell=flowcell, port=params)
    elif isinstance(params, str):
        # skip Valve Command check
        return {"flowcell": flowcell, "port": params}

    return command.model_dump()


def check_pump(
    exp_config: dict,
    last_port: Union[str, int, None],
    flowcell: str,
    params: Union[dict, int, float],
    PumpCommand: BasePumpCommand,
) -> dict:
    """Check and format pump command.

    If only a number is specifed, `volume` will be set to the number,
    and `reagent` will be set to the last reagent specified in the protocol.
    The `flow_rate` will be set to the default reagent flow rate or
    experiment flow rateif not specified in the protocol.

    PUMP: {reagent: str|int, volume: number, flow_rate: number}

    """

    if not isinstance(params, dict):
        params = {"volume": params}
        if last_port is not None:
            params["reagent"] = last_port

    if last_port is not None and "reagent" not in params:
        params["reagent"] = last_port

    reagent = params["reagent"]

    if reagent in exp_config.get("reagents", {}):
        if isinstance(exp_config["reagents"][reagent], dict):
            valve_params = exp_config["reagents"][reagent].copy()
            valve_params.pop("port")
            params = params | valve_params
    else:
        raise ValueError(f"Reagent {reagent} not found in experiment config")

    command = PumpCommand(flowcell=flowcell, **params)

    return command.model_dump()


def check_image(exp_config: dict, params: Union[dict, int], models: dict) -> dict:
    """Check and format image command.

    Cases from most common to least common:

    Case IMAGE: 10
    The number of z planes, `nz`, is set in `ROI` if only an integer is
    specified.
    The default z planes will override z planes specifed as an integer.

    Case IMAGE: {`nz`: 10, `red_laser_power`: 100}
    If a `dict` is specified with imaging parameters, all `ROI`s will
    imaged with these imaging parameters. Missing imaging parameters
    will be set to defaults. Only `nz` will be overridden by the default
    parameter.

    Case IMAGE: {name: `name`,
                 stage: {`nz`: 10, `other_stage_params`},
                 focus: `focus_params`,
                 image: `image_params`}
    If a `dict` is specified with `stage` key and `nz` values, the
    default z planes will not override number of zplanes in specied in
    protocol.

    IMAGE: {image: **image parameters, nz: int}

    """

    # Get defaults
    defaults = deepcopy(exp_config["image"])

    # Format parameters from protocol
    if isinstance(params, dict):
        # params is dictionary = optics and image param key/value, nz is not overrided
        # ptype = dict
        # deep_setdefault(params, defaults)
        dict_command = {}
        dict_command = models["image"](**params).model_dump()  # Validate parameters
        if "nz" in params:
            dict_command["nz"] = params["nz"]
        # Check Stage commands
        if "stage" in params:
            dict_stage = models["stage"](params["stage"]).model_dump()
            dict_command.update({"stage": dict_stage})
        # Check Focus commands
        if "focus" in params:
            dict_focus = models["focus"](params["focus"]).model_dump()
            dict_command.update({"focus": dict_focus})

    elif isinstance(params, int):
        # params is int = number of z planes, overide protocol nz with experiment config nz
        params = {"nz": defaults["nz"]}
        # deep_setdefault(params, defaults)
        dict_command = models["image"](**params).model_dump()  # Validate parameters

    # TODO test this, it probably does not update default stage params with stage params specified in protocol file
    # Check stage commands
    # if ptype is dict and "stage" in params:
    #     dict_stage = models["stage"](params["stage"]).model_dump()
    #     dict_command.update({"stage": dict_stage})

    # TODO test this, it probably does not update default focus params with focus params specified in protocol file
    # Check focus commands
    # if ptype is dict and "focus" in params:
    #     dict_focus = models["focus"](params["focus"]).model_dump()
    #     dict_command.update({"focus": dict_focus})

    return dict_command


def check_expose(exp_config: dict, params: Union[dict, int], models: dict) -> dict:
    # Get defaults
    defaults = exp_config.copy()["expose"]
    for k in defaults.keys():
        if "expose" in k:
            expose_key = k
            break

    # Format parameters from protocol
    if isinstance(params, dict):
        # params is dictionary = optics and expose param key/value
        ptype = dict
    elif isinstance(params, int) or isinstance(params, float):
        # params is int = number of exposures / time of exposure
        ptype = int
        params = {k: params}

    # Overide protocol parameters with experiment config parameters
    deep_setdefault(params, defaults)
    dict_command = models["expose"](**params).model_dump()  # Validate parameters

    if dict_command[expose_key] <= 0:
        raise ValueError(f"Invalid {expose_key} value, should be positive")

    # TODO test this, it probably does not update default stage params with stage params specified in protocol file
    # Check stage commands
    if ptype is dict and "stage" in params:
        stage = models["stage"](params["stage"])
        dict_stage = stage.model_dump()
        dict_command.update({"stage": dict_stage})

    return dict_command


def dispatch_commmand_formatter(
    flowcell: str,
    exp_config: dict,
    command: str,
    params: Any,
    last_port: str,
    models: dict,
) -> dict:
    # Format Commands
    if command in "VALVE":
        fparams = check_valve(flowcell, params)
        last_port = fparams["port"]
    elif command in "PUMP":
        fparams = check_pump(exp_config, last_port, flowcell, params, models["pump"])
        last_port = fparams["reagent"]
    elif command in "HOLD":
        fparams = check_hold(flowcell, params)
    elif command in "WAIT":
        fparams = check_wait(flowcell, params)
    elif command in "USER":
        fparams = check_user(flowcell, params)
    elif command in "IMAGE":
        fparams = check_image(exp_config, params, models)
    elif command in "EXPOSE":
        fparams = check_expose(exp_config, params, models)
    else:
        raise KeyError(f"Unknown command {command}.")

    return fparams, last_port


def format_protocol(flowcell: str, protocols: dict, exp_config: dict) -> dict:
    """Check and format commands to a be more verbose and structured."""

    ExperimentModelFactory = ConfigModelFactory(exp_config)

    StagePosition = ExperimentModelFactory.get_model("stage", BaseStagePosition)
    ImageParams = ExperimentModelFactory.get_model("image", BaseImageParams)
    FocusParams = ExperimentModelFactory.get_model("focus", BaseFocusParams)
    ExposeParams = ExperimentModelFactory.get_model("expose", BaseExposeParams)
    PumpCommand = ExperimentModelFactory.get_model("pump", BasePumpCommand)

    models = {
        "stage": StagePosition,
        "image": ImageParams,
        "focus": FocusParams,
        "expose": ExposeParams,
        "pump": PumpCommand,
    }

    # Loop through protocol, format commands, and count errors
    errors = 0
    fprotocols = {}
    for pname, protocol in protocols.items():
        reformated_steps = []
        last_port = None
        for step_n, step in enumerate(protocol["steps"]):
            command = step[0]
            params = step[1]
            try:
                # format commands
                fparams, last_port = dispatch_commmand_formatter(
                    flowcell, exp_config, command, params, last_port, models
                )
                if "VALV" not in command:
                    # Move VALV commands to PUMP
                    reformated_steps.append((command, fparams))
            # except ValidationError as err:
            #     errors += 1
            #     LOGGER.error(f"Protocol {pname}: step {step_n}: {err}")
            #     reformated_steps.append(("ERROR", command, params))
            except Exception as err:
                errors += 1
                LOGGER.error(f"Protocol {pname}: step {step_n}: {err}")
                reformated_steps.append(("ERROR", command, params))
        protocols[pname].update({"steps": reformated_steps})
        fprotocols[pname] = protocols[pname]

    if errors > 0:
        raise RuntimeError(f"Protocol has {errors} errors. Check the log for details.")
    else:
        LOGGER.debug(f"Formatted {len(protocols)} protocols")

    return fprotocols


def need_reagents(fprotocols: dict, reagents: dict) -> int:
    """Check reagents are defined for flowcells."""
    missing_reagents = []
    for pname, protocol in fprotocols.items():
        for step in protocol["steps"]:
            if "PUMP" in step[0] and isinstance(step[1]["reagent"], str):
                if step[1]["reagent"] not in reagents:
                    missing_reagents.append(step[1]["reagent"])

    missing_reagents = set(missing_reagents)
    for r in missing_reagents:
        warn(f"Missing reagent {r}")
    return len(missing_reagents)


def check_for_rois(fprotocols: dict) -> bool:
    """Check protocol for ROIs, True if ROIs in protocol False if not."""

    for protocol in fprotocols.values():
        for step in protocol["steps"]:
            if "IMAG" in step and "stage" in step["IMAG"]:
                return True
            elif "EXPO" in step and "stage" in step["EXPO"]:
                return True
    return False


def read_user_config(config_path: str) -> dict:
    user_config = tomlkit.parse(open(config_path).read())
    return deep_merge(user_config, DEFAULT_CONFIG.copy())


def deep_setdefault(custom_dict: dict, default_dict: dict):
    """Recursively set default values in custom_dict from default_dict."""
    for k, v in default_dict.items():
        if v == 0:
            v = None
        if k not in custom_dict and v is not None:
            custom_dict[k] = v
        elif isinstance(v, dict) and isinstance(custom_dict[k], dict):
            deep_setdefault(custom_dict[k], v)

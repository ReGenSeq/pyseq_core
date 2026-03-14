from pydantic import (
    BaseModel,
    create_model,
    computed_field,
    PositiveInt,
    PositiveFloat,
    NonNegativeFloat,
    field_validator,
    model_validator,
    DirectoryPath,
)
from pyseq_core.utils import DEFAULT_CONFIG, HW_CONFIG, deep_merge
from functools import cached_property
from typing import Union, Any, Type, Literal
from math import ceil, copysign
from warnings import warn
import yaml
import logging
import tomlkit
from typing_extensions import Self


# Set up logging
LOGGER = logging.getLogger("PySeq")


def custom_params(config: dict) -> dict:
    """Get type and default value pairs for pydantic BaseModel fields from config.

    Use with pydantic.create_model
    """
    kwargs = {}
    for k, v in config.items():
        kwargs[k] = (type(v.unwrap()), v)
    return kwargs


# def recursive_validate(query_dict, valid_dict):
#     """Recursively validate fields in query dictionary.

#     The query dictionary is validated againt a valid dictionary from a config file.
#     Data can be validated between min/max values if min_val and max_val keys are in the config file.
#     Or data can be validate to be in a list if a valid_list key is in the config file.

#     """
#     for k, v in query_dict.items():
#         if isinstance(v, dict) and k in valid_dict and isinstance(valid_dict[k], dict):
#             recursive_validate(v, valid_dict[k])
#         elif "max_val" in valid_dict and "min_val" in valid_dict:
#             validate_min_max(k, v, valid_dict)
#         elif "valid_list" in valid_dict:
#             validate_in(valid_dict[k], v)


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


# def validate_path(value: str) -> str:
#     if Path(value).exists():
#         return value
#     else:
#         msg = f"{value} does not exist"
#         LOGGER.error(msg)
#         raise ValueError


## Consider rewriting class factories like this
# class BaseROIFactory:
#     def __init__(self, config):
#         self.config = config
#     def __call__(self, name: str, flowcell: str = None, **kwargs):
#         # Simplified for example
#         class DynamicROI:
#             def __init__(self, name, flowcell=None, **kwargs):
#                 self.name = name
#                 self.stage = type('Stage', (object,), {'flowcell': flowcell})()
#                 self.kwargs = kwargs
#             def __repr__(self):
#                 return f"DynamicROI(name='{self.name}', flowcell='{self.stage.flowcell}', kwargs={self.kwargs})"
#         return DynamicROI(name, flowcell, **kwargs)


class BaseStagePosition(BaseModel):
    """Stage position information to tile over a region of interest."""

    flowcell: Union[str, int]
    x_init: int
    x_last: int
    y_init: int
    y_last: int
    z_init: int
    nz: int = -1  # Updated by experiment config NOT protocol
    # Not a cached_property because want to change easily
    z_step: PositiveInt = HW_CONFIG["ZStage"]["step"]
    overlap: NonNegativeFloat = 0.0  # in microns

    @computed_field
    @property
    def x(self) -> int:
        return self.x_init

    @computed_field
    @property
    def y(self) -> int:
        return self.y_init

    @computed_field
    @property
    def z(self) -> int:
        return self.z_init

    @computed_field
    @cached_property
    def x_step(self) -> int:
        return HW_CONFIG["XStage"]["step"]

    @computed_field
    @cached_property
    def y_step(self) -> int:
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
    def x_middle(self) -> int:
        return int((self.x_last - self.x_init) / 2 + self.x_init)

    @computed_field
    @property
    def y_middle(self) -> int:
        return int((self.y_last - self.y_init) / 2 + self.y_init)

    @computed_field
    @property
    def z_middle(self) -> int:
        return int((self.z_last - self.z_init) / 2 + self.z_init)

    @computed_field
    @property
    def z_last(self) -> int:
        return self.z_init + self.z_step * self.nz

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
        return int(copysign(1, self.z_last - self.z_init))

    @field_validator("x_init", "x_last", mode="after")
    @classmethod
    def validate_x_pos(cls, value: Union[int, float]) -> Union[int, float]:
        return validate_min_max("position", value, HW_CONFIG["XStage"])

    @field_validator("y_init", "y_last", mode="after")
    @classmethod
    def validate_y_pos(cls, value: Union[int, float]) -> Union[int, float]:
        return validate_min_max("position", value, HW_CONFIG["YStage"])

    @field_validator("z_init", mode="after")
    @classmethod
    def validate_z_pos(cls, value: Union[int, float]) -> Union[int, float]:
        return validate_min_max("position", value, HW_CONFIG["ZStage"])

    @model_validator(mode="after")
    def validate_stage_positions(self) -> Self:
        validate_min_max("position", self.z_last, HW_CONFIG["ZStage"])
        return self


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


class StageFactory:
    @classmethod
    def factory(cls, exp_config: dict = {}) -> Type[BaseStagePosition]:
        config = exp_config.get("stage", {})
        config.update({"nz": exp_config["image"]["nz"]})
        config.update({"overlap": exp_config["image"]["overlap"]})

        ExtraStageParams = create_model("ExtraStageParams", **custom_params(config))

        class StagePosition(ExtraStageParams, BaseStagePosition):
            pass

            @model_validator(mode="after")
            def validate_stage(self) -> Self:
                self_dict = self.model_dump()
                recursive_validate(self_dict, HW_CONFIG["stage"])
                return self

        return StagePosition


# def StageFactory(exp_config: dict) -> BaseModel:
#     """Custom validated stage position information to tile over ROI with default values."""
#     config = exp_config["stage"]
#     config.update({"nz": exp_config["image"]["nz"]})
#     StageParams = create_model("StageParams", **custom_params(config))

#     class StagePosition(StageParams, BaseStagePosition):
#         pass

#         @model_validator(mode="after")
#         def validate_stage(self) -> Self:
#             self_dict = self.model_dump()
#             recursive_validate(self_dict, HW_CONFIG["stage"])
#             return self

#     return StagePosition
ExtraStageParams = create_model("ExtraStageParams", **custom_params(DEFAULT_CONFIG))


class SimpleStage(ExtraStageParams, BaseSimpleStage):
    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        self_dict = self.model_dump()
        recursive_validate(self_dict, HW_CONFIG["stage"])
        return self


SimpleStageType = Type[SimpleStage]

# def SimpleStageFactory(exp_config: dict) -> BaseModel:
#     """Validated X,Y,Z and any extra stage coordinates."""
#     config = exp_config["stage"]
#     # config.update({'nz': exp_config['image']['nz']})
#     SimpleStageParams = create_model("StageParams", **custom_params(config))

#     class SimpleStage(SimpleStageParams, BaseSimpleStage):
#         pass

#         @model_validator(mode="after")
#         def validate_stage(self) -> Self:
#             self_dict = self.model_dump()
#             recursive_validate(self_dict, HW_CONFIG["stage"])
#             return self

#     return SimpleStage


# class BaseOpticsParams(BaseModel):
#     """Empty pydantic BaseModel to hold sequencer specific optical parameters"""
#     pass
UnvalidateOpticsParams = create_model(
    "OpticsParams", **custom_params(DEFAULT_CONFIG["optics"])
)


class OpticsParams(UnvalidateOpticsParams):
    @model_validator(mode="after")
    def validate_optics(self) -> Self:
        self_dict = self.model_dump()
        recursive_validate(self_dict, HW_CONFIG["optics"])
        return self


BaseOpticsParams = Type[OpticsParams]

# class OpticsFactory:
#     @classmethod
#     def factory(cls, exp_config: dict = {}) -> BaseOpticsParams:
#         # DefaultOpticsParams = create_model("OpticsParams", **custom_params(DEFAULT_CONFIG["optics"]))
#         return OpticsParams(**exp_config)


# BaseOpticsParams = create_model("OpticsParams", **custom_params(DEFAULT_CONFIG["optics"]))
# class Optics(OpticsParams):
#     """Custom validated optical parameters"""

#     pass


class ImageParams(BaseModel):
    optics: OpticsParams | None
    image_dir: DirectoryPath | None
    nz: int | None

    @classmethod
    def factory(cls, exp_config: dict) -> Self:
        optics = OpticsParams(**exp_config["image"]["optics"])
        image_dir = exp_config["experiment"].get("images_path", ".")
        nz = exp_config["image"]["nz"]
        return cls(optics=optics, image_dir=image_dir, nz=nz)


# def ImageParamsFactory(exp_config: dict) -> BaseModel:
#     """Custom validated optical parameters for imaging, number of z planes, and output directory."""

#     class ImageParams(BaseModel):
#         optics: BaseOpticsParams = OpticsFactory.factory(exp_config["image"])
#         output: str = exp_config["experiment"]["images_path"]
#         nz: int = exp_config["image"]["nz"]

#         @field_validator("output", mode="after")
#         def validate_ouput(cls, value: str) -> str:
#             return validate_path(value)

#     return ImageParams

AF_ROUTINES = DEFAULT_CONFIG["auto_focus_routines"]["routines"]


class FocusParams(BaseModel):
    optics: OpticsParams | None
    routine: Literal[*AF_ROUTINES] | None  # type: ignore
    output: DirectoryPath | None
    z_focus: Union[int, float] = -1

    @classmethod
    def factory(cls, exp_config: dict = {}) -> Self:
        optics = OpticsParams(**exp_config["focus"]["optics"])
        routine = exp_config["focus"]["routine"]
        output = exp_config["experiment"]["focus_path"]

        return cls(optics=optics, routine=routine, output=output)


# def FocusParamsFactory(exp_config: dict) -> BaseModel:
#     """Custom validated optical parameters for focusing, validated focus routine, and output directory."""

#     class FocusParams(BaseModel):
#         optics: BaseOpticsParams = OpticsParams(**exp_config["focus"])
#         routine: str = exp_config["focus"]["routine"]
#         output: str = exp_config["experiment"]["focus_path"]
#         z_focus: Union[int, float] = -1

#         @field_validator("routine", mode="after")
#         def validate_routine(cls, value):
#             if value not in ["full once", "partial once", "full", "partial"]:
#                 raise ValueError("Invalid autofocusing routine")

#     return FocusParams


class ExposeParams(BaseModel):
    optics: OpticsParams | None
    n_exposures: int | None

    @classmethod
    def factory(cls, exp_config: dict = {}) -> Self:
        optics = OpticsParams(**exp_config["expose"]["optics"])
        n_exposures = exp_config["expose"]["n_exposures"]
        return cls(optics=optics, n_exposures=n_exposures)


# def ExposeParamsFactory(exp_config: dict) -> BaseModel:
#     """Custom validated optical parameters for exposing and number of exposures."""

#     class ExposeParams(BaseModel):
#         optics: BaseOpticsParams = OpticsParams(**exp_config["expose"])
#         n_exposures: int = exp_config["expose"]["n_exposures"]

#     return ExposeParams


class BaseROI(BaseModel):
    name: str
    stage: BaseStagePosition
    image: ImageParams
    focus: FocusParams
    expose: ExposeParams

    @classmethod
    def merge_defaults(
        cls, name: str, stage: dict, extra_params: dict = {}
    ) -> BaseModel:
        # Shallow update stage position parameters with extra parameters
        stage.update(extra_params.pop("stage", {}))
        # Get default parameters
        roi = cls(name=name, stage=stage)
        roi_dict = roi.model_dump()
        # Deep update extra kwargs into roi_dict
        roi_dict = deep_merge(extra_params, roi_dict)
        return cls(**roi_dict)


class ROIFactory:
    @classmethod
    def factory(cls, exp_config: dict = {}) -> Type[BaseROI]:
        StagePosition = StageFactory.factory(exp_config)

        class ROI(BaseROI):
            stage: StagePosition  # type: ignore
            image: ImageParams = ImageParams.factory(exp_config)
            focus: FocusParams = FocusParams.factory(exp_config)
            expose: ExposeParams = ExposeParams.factory(exp_config)

        return ROI


# def BaseROIFactory(exp_config: dict) -> BaseModel:
#     """Custom validated stage, optical, and other parameters to image/focus/expose ROI"""
#     StagePosition = StageFactory.factory(exp_config)
#     ImageParams = ImageParams.factory(exp_config)
#     FocusParams = FocusParams.factory(exp_config)
#     ExposeParams = ExposeParams.factory(exp_config)

#     class Stage(StagePosition):
#         pass

#     class Image(ImageParams):
#         pass

#     class Focus(FocusParams):
#         pass

#     class Expose(ExposeParams):
#         pass

#     class ROI(BaseModel):
#         name: str
#         stage: Stage
#         image: Image = ImageParams()
#         focus: Focus = FocusParams()
#         expose: Expose = ExposeParams()

#     return ROI


class ValveCommand(BaseModel):
    """Validated command to select a port on a valve."""

    port: int
    flowcell: Union[str, int] = None

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
    flowcell: Union[str, int] | None = None


class WaitCommand(BaseModel):
    """Command to pause flowcell until the microscope to available."""

    event: str = "microscope"
    flowcell: Union[str, int] | None = None


class UserCommand(BaseModel):
    """Command to pause flowcell until a user confirms a message."""

    message: str
    timeout: PositiveFloat | None = None
    flowcell: Union[str, int, None] = None


class BasePumpCommand(BaseModel):
    """Partially validated command to pump a reagent. '

    Volume in uL and flow rate in uL/min are validated.
    Reagent is not validated.
    """

    volume: PositiveFloat
    flow_rate: PositiveFloat
    reagent: Union[int, str] = None
    reverse: bool = False
    flowcell: Union[str, int] = None

    @model_validator(mode="after")
    def validate_flowrate_volume(self) -> Self:
        if self.flow_rate != 0:
            validate_min_max(
                "flow_rate", self.flow_rate, HW_CONFIG[f"Pump{self.flowcell}"]
            )
        validate_min_max("volume", self.volume, HW_CONFIG[f"Pump{self.flowcell}"])
        if isinstance(self.reagent, int):
            validate_in("port", self.reagent, HW_CONFIG[f"Valve{self.flowcell}"])
        return self


class PumpCommandFactory:
    """Create custom partially validated command to pump a reagent. '

    Volume in uL and flow rate in uL/min are validated.
    Reagent is not validated.
    """

    @classmethod
    def factory(cls, exp_config: dict = {}) -> Type[BasePumpCommand]:
        UserPumpParams = create_model(
            "UserPumpParams", **custom_params(exp_config["pump"])
        )

        class PumpCommand(UserPumpParams, BasePumpCommand):
            @model_validator(mode="after")
            def validate_pump(self) -> Self:
                self_dict = self.model_dump()
                recursive_validate(self_dict, HW_CONFIG[f"Pump{self.flowcell}"])
                return self

        return PumpCommand


# def  PumpCommandFactory(exp_config) -> BaseModel:
#     """Custom partially validated command to pump a reagent. '

#     Volume in uL and flow rate in uL/min are validated.
#     Reagent is not validated.
#     """
#     UserPumpParams = create_model("UserPumpParams", **custom_params(exp_config["pump"]))

#     class PumpCommand(UserPumpParams, BasePumpCommand):
#         @model_validator(mode="after")
#         def validate_pump(self) -> Self:
#             self_dict = self.model_dump()
#             recursive_validate(self_dict, HW_CONFIG[f"Pump{self.flowcell}"])
#             return self

#     return PumpCommand


def simple_txt_to_yaml(file_path: str) -> dict:
    modified_yaml = ""
    with open(file_path, "r") as file:
        for line in file:
            stripped_line = line.strip()
            if stripped_line:
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
    flowcell: str, params: Union[dict, int, float], PumpCommand: BasePumpCommand
) -> dict:
    """Check and format pump command.

    If only a number is specifed, `volume` will be set to the number,
    `flow_rate` will be set to 0, and `reagent` will be set to the last reagent
    specified in the protocol. The updated `flow_rate` will then be pulled from
    the reagent dictionary stored on the VALVE.

    PUMP: {reagent: str|int, volume: number, flow_rate: number}

    """

    if isinstance(params, dict):
        command = PumpCommand(flowcell=flowcell, **params)
    else:
        command = PumpCommand(flowcell=flowcell, volume=params)

    return command.model_dump()


def check_image(
    exp_config: dict, params: Union[dict, int], StagePosition: BaseStagePosition
) -> dict:
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

    defaults = exp_config.copy()

    # Get default nz in experiment config to override protocol nz
    if exp_config["image"]["nz"] > 0:
        nz = exp_config["image"]["nz"]
    else:
        nz = None

    # Get default nz in experiment config to override protocol nz
    # if StagePosition.model_fields["nz"].default > 0:
    #     nz = StagePosition.model_fields["nz"].default
    # else:
    #     nz = None

    # Format parameters from protocol
    if isinstance(params, dict):
        ptype = dict
        # params is dictionary = optics and image param key/value, nz is not overrided
        defaults.update(params)
        dict_command = ImageParams.factory(defaults).model_dump()  # Validate parameters
        if nz is not None:
            # Overide protocol nz  with experiment nz
            dict_command.update({"nz": nz})
    elif isinstance(params, int):
        ptype = int
        # params is int = number of z planes
        if nz is None:
            defaults["image"].update({"nz": params})
        else:
            # Overide protocol nz  with experiment nz
            defaults["image"].update({"nz": nz})
        dict_command = ImageParams.factory(defaults).model_dump()
    elif params is None and nz is None:
        # nz was never specified, raise Error
        raise KeyError("Number of z planes to image, nz, is not specified")

    # TODO test this, it probably does not update default stage params with stage params specified in protocol file
    # Check stage commands
    if ptype is dict and "stage" in params:
        dict_stage = StagePosition(params["stage"]).model_dump()
        dict_command.update({"stage": dict_stage})

    # TODO test this, it probably does not update default focus params with focus params specified in protocol file
    # Check focus commands
    if ptype is dict and "focus" in params:
        dict_focus = FocusParams.factory(defaults).model_dump()
        dict_command.update({"focus": dict_focus})
        # deep_merge(dict_focus["optics"], dict_command["focus"]["optics"])
    return dict_command


def check_expose(
    exp_config: dict, params: Union[dict, int], StagePosition: BaseStagePosition
) -> dict:
    defaults = exp_config.copy()

    # Get default n_exposures in experiment config to override protocol n_exposures
    n_exposures = defaults["expose"]["n_exposures"]

    # Format parameters from protocol
    if isinstance(params, dict):
        # params is dictionary = optics and expose param key/value
        ptype = dict
        defaults.update(params)
        dict_command = ExposeParams.factory(
            defaults
        ).model_dump()  # Validate parameters
        if n_exposures > 0:
            # Overide protocol n_exposures with experiment config n_exposures
            dict_command.update({"n_exposures": n_exposures})
    elif isinstance(params, int):
        # params is int = number of exposures
        ptype = int
        if n_exposures == 0:
            defaults["expose"].update({"n_exposures": params})
        else:
            # Overide protocol n_exposures with experiment config n_exposures
            defaults["expose"].update({"n_exposures": n_exposures})
        dict_command = ExposeParams(defaults).model_dump()
    elif params is None and n_exposures is None:
        # nz was never specified, raise Error
        raise KeyError("Number of exposures, n_exposures, is not specified")

    # TODO test this, it probably does not update default stage params with stage params specified in protocol file
    # Check stage commands
    if ptype is dict and "stage" in params:
        stage = StagePosition(params["stage"])
        dict_stage = stage.model_dump()
        dict_command.update({"stage": dict_stage})

    return dict_command


def dispatch_commmand_formatter(
    flowcell: str, exp_config: dict, command: str, params: Any, last_port: str
) -> dict:
    # # Create default parameters from user exp_config
    StagePosition = StageFactory.factory(exp_config)
    # ImageParams = ImageParams.factory(exp_config)
    # FocusParams = FocusParams.factory(exp_config)
    # ExposeParams = ExposeParams.factory(exp_config)
    PumpCommand = PumpCommandFactory.factory(exp_config)

    # Format Commands
    if command in "VALVE":
        fparams = check_valve(flowcell, params)
        last_port = fparams["port"]
    elif command in "PUMP":
        fparams = check_pump(flowcell, params, PumpCommand)
        if fparams["reagent"] is None:
            fparams["reagent"] = last_port
        else:
            last_port = fparams["reagent"]
    elif command in "HOLD":
        fparams = check_hold(flowcell, params)
    elif command in "WAIT":
        fparams = check_wait(flowcell, params)
    elif command in "USER":
        fparams = check_user(flowcell, params)
    elif command in "IMAGE":
        fparams = check_image(exp_config, params, StagePosition)
    elif command in "EXPOSE":
        fparams = check_expose(exp_config, params, StagePosition)
    else:
        raise KeyError(f"Unknown command {command}.")

    return fparams, last_port


def format_protocol(flowcell: str, protocols: dict, exp_config: dict) -> dict:
    """Check and format commands to a be more verbose and structured."""

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
                    flowcell, exp_config, command, params, last_port
                )
                if "VALV" not in command:
                    # Move VALV commands to PUMP
                    reformated_steps.append((command, fparams))
            except Exception as err:
                errors += 1
                LOGGER.error(f"Protocol {pname}: step {step_n}: {err}")
                reformated_steps.append(("ERROR", command, fparams))
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

    for pname, protocol in fprotocols.items():
        for step in protocol["steps"]:
            if "IMAG" in step and "stage" in step["IMAG"]:
                return True
            elif "EXPO" in step and "stage" in step["EXPO"]:
                return True
    return False


def read_user_config(config_path: str) -> dict:
    user_config = tomlkit.parse(open(config_path).read())
    return deep_merge(user_config, DEFAULT_CONFIG.copy())

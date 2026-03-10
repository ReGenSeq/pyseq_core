from __future__ import annotations
from attrs import define, field
from pyseq_core.base_protocol import ROIFactory
from pyseq_core.utils import DEFAULT_CONFIG  # #HW_CONFIG, deep_merge

from warnings import warn
from typing import Union, Dict, Callable, Any, Type, TYPE_CHECKING
import logging
import tomlkit
from asyncio import Condition

if TYPE_CHECKING:
    from pyseq_core.base_system import BaseFlowCell

LOGGER = logging.getLogger("PySeq")


DefaultROI = ROIFactory.factory(DEFAULT_CONFIG)
ROIType = Type[DefaultROI]


# class DefaultROI(_DefaultROI):
#     pass


def read_roi_config(
    flowcells: str,
    config_path: str,
    exp_config: dict = {},
    custom_roi_stage: Callable[[str, Union[int, str], Any], ROIType] = None,
) -> list[ROIType]:
    """Read ROI toml file and return list of ROIs.

    TOML file can be in any of the following forms

    [flowcell]
    roi_name: {custom roi kwargs}
    ---
    [roi_name]:
    flowcell: fc
    custom roi kwarg: kwarg
    ---
    [roi_name]:
    stage: stage kwargs
    image: {optics: optics kwargs, **image kwargs}
    focus: {optics: optics kwargs, **focus kwargs}
    expose: {optics: optics kwargs, **expose kwargs}

    Can pass custom_roi_factory callable to parse kwargs and return ROI.

    """
    """Reads an ROI configuration TOML file and returns a list of ROI objects.

    This function parses a TOML file that defines various Regions of Interest (ROIs).
    It supports different formats for the TOML file and can optionally use a
    custom factory function to create ROI objects.

    TOML file can be in any of the following forms:

    1.  **Flowcell-centric:**
        ```toml
        [flowcell_name]
        roi_name_1 = { custom_roi_kwarg_a = "value", custom_roi_kwarg_b = 123 }
        roi_name_2 = { ... }
        ```
        In this format, the top-level key is the flowcell name, and nested keys
        are ROI names with their custom keyword arguments.

    2.  **ROI-centric (explicit flowcell):**
        ```toml
        [roi_name_1]
        flowcell = "fc_name"
        custom_roi_kwarg_c = "another_value"
        ```
        Here, each top-level key is an ROI name, and it explicitly specifies
        its `flowcell` within its section.

    3.  **Standard ROI definition (with instrument-specific kwargs):**
        ```toml
        [roi_name_2]
        stage = { stage_kwarg_x = 10.0 }
        image = { optics = { optics_kwarg_y = "zoom" }, image_kwarg_z = true }
        focus = { optics = { ... }, focus_kwarg_a = 0.5 }
        expose = { optics = { ... }, expose_kwarg_b = 100 }
        ```
        This format defines an ROI with detailed configurations for various
        instrument modules (stage, image, focus, expose).

    Args:
        flowcells (Union[str, list[str]]): A single flowcell name (str) or a list
            of flowcell names (list of str) for which to load ROIs. Only ROIs
            associated with these flowcells will be returned.
        config_path (str): The file path to the TOML configuration file containing
            the ROI definitions.
        exp_config (dict, optional): An optional experiment configuration dictionary.
            If provided, a `BaseROIFactory` will be initialized with this config
            to create ROI objects. If None, `DefaultROI` is used. Defaults to None.
        custom_roi_stage (Callable[[str, Union[int, str], Any], DefaultROI], optional):
            A callable (function or class) that takes `flowcell`, a custom ROI constructor, and
            `**kwargs` as arguments and returns dictionary of parameters for `StagePosition`. 
            This allows for custom parsing of real world coordinates and conversion
            to sequencer specific stage coordinates and. 

    Returns:
        list[DefaultROI]: A list of `DefaultROI` objects (or objects created
            by `custom_roi_factory`) that match the specified `flowcells`.
    """

    roi_config = tomlkit.parse(open(config_path).read())

    if exp_config is not None:
        ROI = ROIFactory.factory(exp_config)
    else:
        ROI = DefaultROI

    rois = []
    for roi_name, _roi in roi_config.items():
        fc = _roi.get("flowcell", None)
        if roi_name in flowcells and fc is None:
            # {flowcell: {roi_name: **custom_roi_kwargs}
            fc = roi_name
            for roi_name_, roi_ in _roi.items():
                stage = custom_roi_stage(fc, **roi_)
                rois.append(ROI.merge_defaults(roi_name_, stage, roi_))

        elif fc is not None and fc in flowcells:
            # {roi_name: {flowcell: fc, **custom_roi_kwargs}
            stage = custom_roi_stage(**_roi)
            rois.append(ROI.merge_defaults(roi_name, stage, _roi))
        else:
            # {roi_name: name, stage: **stage_kwargs, image:**image_kwargs, ...}
            rois.append(ROI(name=roi_name, **_roi))
    return rois


@define
class ROIManager:
    flowcells: Dict[Union[str, int], BaseFlowCell] = field(factory=dict)
    roi_condition: Condition = field(factory=Condition)
    """Manages Regions of Interest (ROIs) across different flowcells.

    This class provides functionalities to add, update, remove, and retrieve ROIs,
    organizing them by flowcell. It also includes a mechanism to wait for ROIs
    to be available, useful in asynchronous experiment workflows.

    Attributes:
        flowcells (dict): A dictionary where keys are flowcell names (str) and
            values are instances of `BaseFlowcell`.
        roi_condition (Condition): A threading.Condition object used to wait
            for ROIs to be added to a flowcell before starting an experiment.
    """

    def rois(self, flowcell: Union[str, int]) -> dict:
        """Retrieves the dictionary of ROIs for a specific flowcell.

        Args:
            flowcell (str, int): The name of the flowcell.

        Returns:
            dict: A dictionary mapping ROI names to `DefaultROI` objects for the
                specified flowcell.
        """
        return self.flowcells[flowcell].ROIs

    def add(self, roi: ROIType = None, exp_config: dict = None, **kwargs) -> bool:
        """Adds a Region of Interest (ROI) to a flowcell.

        If an `roi` object is provided, it is added directly. Otherwise, a new
        ROI object is created using `DefaultROI` or a `BaseROIFactory` (if
        `exp_config` is provided) and then added. The ROI is added to the
        appropriate flowcell based on `roi.stage.flowcell`.

        Args:
            roi (DefaultROI, optional): An existing `DefaultROI` object to add.
                If None, a new ROI will be created using `kwargs`. Defaults to None.
            exp_config (dict, optional): An optional experiment configuration
                dictionary used to initialize `BaseROIFactory` if a new ROI
                is being created. Defaults to None.
            **kwargs: Keyword arguments used to create a new `DefaultROI` if `roi`
                is None. These are passed directly to the ROI constructor.

        Raises:
            UserWarning: If an ROI with the same name already exists on the
                target flowcell.
        """

        if exp_config is not None:
            ROI = ROIFactory.factory(exp_config)
        else:
            ROI = DefaultROI

        if roi is None:
            roi = ROI(**kwargs)
        fc = roi.stage.flowcell
        if roi.name not in self.rois(fc):
            self.rois(fc)[roi.name] = roi
            LOGGER.info(f"Added {roi.name} to flowcell {fc}")
            LOGGER.debug(f"{roi}")
            return True
        else:
            msg = f"{roi.name} already exists on flowcell {fc}"
            LOGGER.warning(msg)
            warn(msg, UserWarning)
            return False

    def update(self, roi: ROIType):
        """Updates an existing Region of Interest (ROI) on a flowcell.

        If an ROI with the same name exists on the target flowcell, it is
        replaced with the provided `roi` object.

        Args:
            roi (DefaultROI): The `DefaultROI` object to update. Its `name`
                and `stage.flowcell` attributes are used to identify the ROI
                to be updated.

        Raises:
            UserWarning: If the ROI to be updated does not exist on the
                target flowcell.
        """

        fc = roi.stage.flowcell
        if roi.name in self.rois(fc):
            LOGGER.debug(f"{self.rois(fc)[roi.name]}")
            self.rois(fc)[roi.name] = roi
            LOGGER.info("Updated {roi.name} on flowcell {fc}")
            LOGGER.debug(f"{roi}")
        else:
            msg = f"{roi.name} does not exist on flowcell {fc}"
            LOGGER.warning(msg)
            warn(msg, UserWarning)

    def remove(self, flowcell: str, roi: str):
        """Removes a Region of Interest (ROI) from a specific flowcell.

        Args:
            flowcell (str): The name of the flowcell from which to remove the ROI.
            roi_name (str): The name of the ROI to remove.
        """
        if roi in self.rois(flowcell):
            del self.rois(flowcell)[roi]

    async def wait_for_rois(self, flowcell: str):
        """Waits for ROIs to be added to a specific flowcell.

        This method uses a threading.Condition to block until at least one ROI
        is present in the specified flowcell's ROI dictionary. This is useful
        for synchronization in multi-threaded or asynchronous environments
        where ROIs might be added dynamically.

        Args:
            flowcell (str): The name of the flowcell to wait for ROIs on.
        """

        async with self.roi_condition:
            if len(self.rois(flowcell)) == 0:
                LOGGER.info(f"Waiting for ROIs on flowcell {flowcell}")
            await self.roi_condition.wait_for(lambda: len(self.rois(flowcell)) > 0)
            LOGGER.info(f"{len(self.rois(flowcell))} ROIs on flowcell {flowcell}")

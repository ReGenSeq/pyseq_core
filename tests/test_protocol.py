import pytest
import importlib
from shutil import copyfile
from pyseq_core.utils import deep_merge, DEFAULT_CONFIG
import tomlkit
from copy import deepcopy
from typing import Any


def check_reagents(exp_conf, reagents):
    """Check reagents loaded in flowcell match experiment configuration."""
    default_params = exp_conf["pump"]

    assert len(reagents) == len(exp_conf["reagents"]), "Reagents count mismatch"

    for reagent, _params in exp_conf["reagents"].items():
        params = default_params.copy()
        if isinstance(_params, dict):
            params.update(_params)
        elif isinstance(_params, int):
            params["port"] = _params
        else:
            assert False, f"Invalid reagent parameters for {reagent}: {_params}"

        assert dict_recursive_check(params, reagents[reagent])

        # for key, value in params.items():
        #     assert reagents[reagent][key] == value, f"Reagent {reagent} {key} mismatch: {reagents[reagent][key]} != {value}"


def dict_recursive_check(d_in: Any, d_out: Any):
    if isinstance(d_in, dict):
        for key, val in d_in.items():
            if isinstance(val, dict):
                dict_recursive_check(val, d_out[key])
            else:
                val_out = d_out[key]
                if not val == val_out:
                    print(f"Mismatch for key '{key}': {val} != {val_out}")
                    assert val == val_out
    return True


def check_roi_params(in_params, out_params):
    for mode in ["image", "focus", "expose"]:
        # update and merge user parameters into default parameters
        # Somehow DEFAULT_CONFIG is updated with experiment configuration?
        defaults = deepcopy(DEFAULT_CONFIG[mode])
        roi_in = deep_merge(in_params, defaults)
        try:
            assert dict_recursive_check(roi_in.get(mode, {}), out_params[mode])
        # except AssertionError:
        except Exception:
            fc = out_params["stage"]["flowcell"]
            name = out_params["name"]
            print(f"flowcell={fc}, roi={name}")
            print(f"Error with mode={mode}")
            print("Default parameters:")
            print(defaults)
            print(f"Input for {name}")
            print(in_params)
            print("ROI input")
            print(roi_in)
            print(f"Parsed ROI for {name}")
            print(out_params)
            assert False


def check_ROIs(exp_conf, ROIs):
    """Check ROIs loaded in flowcell match experiment configuration and ROI file."""
    # Read and parse the ROI file
    roi_conf = tomlkit.parse(open(exp_conf["experiment"]["roi_path"]).read())
    roi_table = {}
    for fc, _roi in roi_conf.items():
        if isinstance(_roi, dict) and "flowcell" in _roi:
            # roi_name = {flowcell=fc, ...}
            name = fc
            roi_table.setdefault(_roi["flowcell"], {})
            roi_table[_roi["flowcell"]].update({name: _roi})
        elif isinstance(_roi, dict) and "flowcell" not in _roi:
            # flowcell = {roi_name:{...}, ...}
            roi_table.setdefault(fc, {})
            roi_table[fc].update(_roi)

    for name, params in ROIs.items():
        fc = params.stage.flowcell
        check_roi_params(roi_table[fc][name], params.model_dump())


@pytest.mark.asyncio
async def test_protocol(BaseTestSequencer, tmp_path, caplog):
    # Read test experiment configuration
    resource_path = importlib.resources.files("pyseq_core") / "resources"
    exp_file = "test_experiment.toml"
    exp_path = resource_path / "test_experiment.toml"
    exp_conf = tomlkit.parse(open(exp_path).read())
    exp_name = exp_conf["experiment"]["name"]
    exp_conf["ROTATE_LOGS"] = True

    # Update paths in experiment configuration
    protocol_file = "test_protocol.yaml"
    roi_file = "test_roi.toml"
    exp_conf["experiment"]["output_path"] = str(tmp_path)
    exp_conf["experiment"]["protocol_path"] = str(tmp_path / protocol_file)
    exp_conf["experiment"]["roi_path"] = str(tmp_path / roi_file)

    # Write updated experiment and protocol/rois to temp directory
    with open(tmp_path / exp_file, "w") as f:
        tomlkit.dump(exp_conf, f)
    copyfile(resource_path / protocol_file, tmp_path / protocol_file)
    copyfile(resource_path / roi_file, tmp_path / roi_file)

    BaseTestSequencer.new_experiment(["A", "B"], tmp_path / exp_file, exp_name)
    await BaseTestSequencer._queue.join()

    # Check paths are created
    assert (tmp_path / exp_name).exists()
    paths = ["images", "focus", "log"]
    for p in paths:
        assert (tmp_path / exp_name / p).exists()
    assert (tmp_path / exp_name / f"log/{exp_name}.log").exists()

    # Check protocol is queued
    assert len(BaseTestSequencer.flowcells["A"]._queue_dict) > 0
    assert len(BaseTestSequencer.flowcells["B"]._queue_dict) > 0

    # Check rois are loaded
    for fc in BaseTestSequencer.flowcells.values():
        check_ROIs(exp_conf, fc.ROIs)

    # Check reagents are loaded
    for fc in BaseTestSequencer.flowcells.values():
        check_reagents(exp_conf, fc.reagents)

    # Clear Queue and start flowcells for clean teardown
    await BaseTestSequencer.flowcells["A"].clear_queue()
    await BaseTestSequencer.flowcells["B"].clear_queue()
    await BaseTestSequencer.microscope.clear_queue()
    await BaseTestSequencer.clear_queue()

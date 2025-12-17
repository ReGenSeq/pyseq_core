def test_add_rois(BaseTestSequencer, test_roi_file_path):
    BaseTestSequencer.add_rois(["A", "B"], test_roi_file_path)

    for fc in BaseTestSequencer._get_systems_list("flowcell"):
        assert len(fc.ROIs) == 3

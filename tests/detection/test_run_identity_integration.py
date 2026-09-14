import pytest

import run_detection as line_main

from tracking_parking.common.run_identity import build_condition_key


BASE_RUN_CONFIG = {
    "logic_name": "line_detection",
    "input_type": "file",
    "input_sha256": "video-a",
    "model_sha256": "model-a",
    "line1_points": [[0.0, 0.0], [10.0, 0.0]],
    "line2_points": [[0.0, 10.0], [10.0, 10.0]],
    "parking_reference_point": [5.0, 20.0],
    "vehicle_classes": [2, 7],
    "method": "hybrid",
    "margin_px": 0.0,
    "endpoint_margin_px": 0.0,
    "crossing_method": "hysteresis_v1",
    "max_frame_gap": 90,
    "cleanup_threshold": 150,
    "yolo_conf": 0.3,
    "yolo_iou": 0.3,
    "yolo_device": "cpu",
    "yolo_imgsz": 640,
    "tracker_config": "botsort.yaml",
}


def test_line_condition_contains_all_geometry():
    condition = line_main.build_line_condition(BASE_RUN_CONFIG)
    assert condition["line1_points"] == BASE_RUN_CONFIG["line1_points"]
    assert condition["line2_points"] == BASE_RUN_CONFIG["line2_points"]
    assert (
        condition["parking_reference_point"]
        == BASE_RUN_CONFIG["parking_reference_point"]
    )


@pytest.mark.parametrize(
    ("field", "different_value"),
    [
        ("line1_points", [[1.0, 0.0], [10.0, 0.0]]),
        ("line2_points", [[0.0, 11.0], [10.0, 10.0]]),
        ("parking_reference_point", [6.0, 20.0]),
    ],
)
def test_each_geometry_change_changes_integrated_condition_key(field, different_value):
    base = line_main.build_line_condition(BASE_RUN_CONFIG)
    changed_config = {**BASE_RUN_CONFIG, field: different_value}
    changed = line_main.build_line_condition(changed_config)
    assert build_condition_key(base) != build_condition_key(changed)

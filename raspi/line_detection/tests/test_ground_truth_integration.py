import importlib.util
import sys
from pathlib import Path

import pytest


LINE_ROOT = Path(__file__).parents[1]
RASPI_ROOT = LINE_ROOT.parent
sys.path.insert(0, str(LINE_ROOT))
sys.path.insert(0, str(RASPI_ROOT))

spec = importlib.util.spec_from_file_location(
    "line_detection_main_ground_truth", LINE_ROOT / "main.py"
)
line_main = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = line_main
spec.loader.exec_module(line_main)

from common.run_identity import build_condition_key


BASE_RUN_CONFIG = {
    "logic_name": "line_detection",
    "input_type": "file",
    "input_sha256": "video-a",
    "model_sha256": "model-a",
    "line1_points": [[0.0, 0.0], [10.0, 0.0]],
    "line2_points": [[0.0, 10.0], [10.0, 10.0]],
    "parking_reference_point": [5.0, 20.0],
    "ground_truth_config": "/tmp/gt.json",
    "ground_truth_sha256": "gt-hash-a",
    "gt_in": 22,
    "gt_out": 0,
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


def test_line_condition_includes_ground_truth_identity_keys():
    condition = line_main.build_line_condition(BASE_RUN_CONFIG)
    assert condition["ground_truth_sha256"] == BASE_RUN_CONFIG["ground_truth_sha256"]
    assert condition["gt_in"] == BASE_RUN_CONFIG["gt_in"]
    assert condition["gt_out"] == BASE_RUN_CONFIG["gt_out"]
    assert "ground_truth_config" not in condition


@pytest.mark.parametrize(
    ("field", "different_value"),
    [
        ("ground_truth_sha256", "gt-hash-b"),
        ("gt_in", 23),
        ("gt_out", 1),
    ],
)
def test_each_ground_truth_change_changes_condition_key(field, different_value):
    base = line_main.build_line_condition(BASE_RUN_CONFIG)
    changed_config = {**BASE_RUN_CONFIG, field: different_value}
    changed = line_main.build_line_condition(changed_config)
    assert build_condition_key(base) != build_condition_key(changed)


def test_ground_truth_path_does_not_change_condition_key():
    base = line_main.build_line_condition(BASE_RUN_CONFIG)
    changed_config = {**BASE_RUN_CONFIG, "ground_truth_config": "/tmp/other_gt.json"}
    changed = line_main.build_line_condition(changed_config)
    assert build_condition_key(base) == build_condition_key(changed)

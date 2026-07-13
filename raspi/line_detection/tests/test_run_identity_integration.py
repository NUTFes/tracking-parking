import importlib.util
import sys
from pathlib import Path

import pytest


LINE_ROOT = Path(__file__).parents[1]
RASPI_ROOT = LINE_ROOT.parent
sys.path.insert(0, str(LINE_ROOT))
sys.path.insert(0, str(RASPI_ROOT))

spec = importlib.util.spec_from_file_location(
    "line_detection_main_identity", LINE_ROOT / "main.py"
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
    "vehicle_classes": [2, 7],
    "method": "hybrid",
    "margin": 1000.0,
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

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2]))

analysis = importlib.import_module("scripts.02_run_analysis")
from src.counter import Counter


def test_build_state_metrics_separates_detection_state_and_archive_counts():
    counter = Counter()
    counter.update(1, 0.1, 0)
    counter.update(1, 0.8, 1)
    counter.cleanup(152)

    metrics = analysis.build_state_metrics(counter, active_detections=4)

    assert metrics == {
        "active_detections": 4,
        "retained_states": 0,
        "archived_events": 1,
    }

import csv
import json
import sys
from pathlib import Path

import pytest


RASPI_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(RASPI_ROOT))

from common.event_matching import PredictedEvent, match_events
from common.ground_truth import GroundTruth, GtEvent
from eval.build_event_accuracy_rows import build_eval_row, write_eval_rows


def make_ground_truth() -> GroundTruth:
    return GroundTruth(
        path=None,
        sha256=None,
        gt_in=1,
        gt_out=1,
        events=(
            GtEvent(event_id="gt-in", direction="IN", t_sec=10.0),
            GtEvent(event_id="gt-out", direction="OUT", t_sec=30.0),
        ),
        tolerance_sec=0.5,
    )


def make_predicted_events() -> list[PredictedEvent]:
    return [
        PredictedEvent(event_id="pred-in", direction="IN", t_sec=10.2),
        PredictedEvent(event_id="pred-out", direction="OUT", t_sec=30.0),
        PredictedEvent(event_id="pred-fp", direction="IN", t_sec=100.0),
    ]


def test_build_eval_row_matches_event_matching_and_threads_run_identity():
    predicted = make_predicted_events()
    gt = make_ground_truth()

    expected = match_events(predicted, gt.events, gt.tolerance_sec)
    row = build_eval_row(
        predicted,
        gt,
        wandb_run_id="run-1",
        execution_id="execution-1",
        condition_key="condition-1",
    )

    assert row["wandb_run_id"] == "run-1"
    assert row["execution_id"] == "execution-1"
    assert row["condition_key"] == "condition-1"
    assert row["tp"] == expected.tp == 2
    assert row["fp"] == expected.fp == 1
    assert row["fn"] == expected.fn == 0
    assert row["precision"] == expected.precision == pytest.approx(2 / 3)
    assert row["recall"] == expected.recall == 1.0
    assert row["f1"] == expected.f1 == pytest.approx(0.8)


def test_write_eval_rows_json_round_trips(tmp_path):
    rows = [
        {
            "wandb_run_id": "run-1",
            "execution_id": None,
            "condition_key": "condition-1",
            "tp": 2,
            "fp": 1,
            "fn": 0,
            "precision": 2 / 3,
            "recall": 1.0,
            "f1": 0.8,
        }
    ]
    output_path = tmp_path / "nested" / "rows.json"

    written_path = write_eval_rows(rows, output_path)

    assert written_path == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == rows


def test_write_eval_rows_csv_round_trips(tmp_path):
    rows = [
        {
            "wandb_run_id": "run-1",
            "execution_id": None,
            "condition_key": "condition-1",
            "tp": 2,
            "fp": 1,
            "fn": 0,
            "precision": 2 / 3,
            "recall": 1.0,
            "f1": 0.8,
        }
    ]
    output_path = tmp_path / "rows.csv"

    write_eval_rows(rows, output_path)

    with output_path.open(newline="", encoding="utf-8") as file:
        actual_rows = list(csv.DictReader(file))
    expected_row = {
        key: "" if value is None else str(value)
        for key, value in rows[0].items()
    }
    assert actual_rows == [expected_row]


def test_write_eval_rows_rejects_unsupported_extension(tmp_path):
    with pytest.raises(ValueError):
        write_eval_rows([], tmp_path / "rows.txt")


def test_write_eval_rows_creates_missing_parent_directories(tmp_path):
    output_path = tmp_path / "missing" / "parents" / "rows.json"

    write_eval_rows([], output_path)

    assert output_path.is_file()

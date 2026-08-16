import csv
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))          # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))  # roi-counter/scripts/
sys.path.insert(0, str(Path(__file__).parents[2]))           # raspi/（common 共有のため）

report = importlib.import_module("05_build_accuracy_report")


EVENT_COLUMNS = (
    "s_low", "s_high", "video", "track_id", "event_type",
    "frame_index", "timestamp_sec", "is_warmup", "event_id",
)


def write_ground_truth(video_source: Path, *, events=None, tolerance_sec=0.5):
    data = {
        "video": video_source.name,
        "in": sum(event["direction"] == "IN" for event in events or []),
        "out": sum(event["direction"] == "OUT" for event in events or []),
        "tolerance_sec": tolerance_sec,
    }
    if events is not None:
        data["events"] = events
    gt_path = video_source.with_name(f"{video_source.stem}_gt.json")
    gt_path.parent.mkdir(parents=True, exist_ok=True)
    gt_path.write_text(json.dumps(data), encoding="utf-8")


def write_manifest(
    run_dir: Path,
    name: str,
    video_source: Path,
    *,
    s_low=0.25,
    s_high=0.75,
    execution_id="execution-1",
    condition_key="condition-1",
    wandb_run_id=None,
):
    manifest = {
        "condition_key": condition_key,
        "execution_id": execution_id,
        "wandb_run_id": wandb_run_id,
        "config": {
            "input_source": str(video_source),
            "s_low": s_low,
            "s_high": s_high,
        },
    }
    manifest_path = run_dir / "manifests" / name
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def write_events(run_dir: Path, rows: list[dict]):
    with (run_dir / "events.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=EVENT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def event_row(
    *,
    s_low=0.25,
    s_high=0.75,
    video="clip.MOV",
    event_id="pred-1",
    timestamp_sec="10.2",
    event_type="IN",
):
    return {
        "s_low": s_low,
        "s_high": s_high,
        "video": video,
        "track_id": "track-1",
        "event_type": event_type,
        "frame_index": "100",
        "timestamp_sec": timestamp_sec,
        "is_warmup": "False",
        "event_id": event_id,
    }


def run_report(monkeypatch, run_dir: Path, output_path: Path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "05_build_accuracy_report.py",
            "--run-dir",
            str(run_dir),
            "--output",
            str(output_path),
        ],
    )
    report.main()


def test_builds_eval_row_from_matching_predicted_events(tmp_path, monkeypatch):
    run_dir = tmp_path / "mae_20260817_120000"
    video_source = tmp_path / "data" / "inputs" / "clip.MOV"
    write_ground_truth(
        video_source,
        events=[
            {"event_id": "gt-in", "direction": "IN", "t_sec": 10.0},
            {"event_id": "gt-out", "direction": "OUT", "t_sec": 30.0},
        ],
    )
    write_manifest(run_dir, "execution-1.json", video_source, wandb_run_id=None)
    write_events(
        run_dir,
        [
            event_row(event_id="pred-in", timestamp_sec="10.2"),
            event_row(event_id="pred-out", timestamp_sec="30.0", event_type="OUT"),
            event_row(event_id="pred-fp", timestamp_sec="100.0"),
        ],
    )

    output_path = tmp_path / "eval" / "rows.json"
    run_report(monkeypatch, run_dir, output_path)

    rows = json.loads(output_path.read_text(encoding="utf-8"))
    assert rows == [
        {
            "wandb_run_id": None,
            "execution_id": "execution-1",
            "condition_key": "condition-1",
            "tp": 2,
            "fp": 1,
            "fn": 0,
            "precision": pytest.approx(2 / 3),
            "recall": 1.0,
            "f1": pytest.approx(0.8),
        }
    ]


def test_skips_manifest_without_per_event_ground_truth(tmp_path, monkeypatch, capsys):
    run_dir = tmp_path / "mae_20260817_120001"
    video_source = tmp_path / "data" / "inputs" / "unannotated.MOV"
    write_ground_truth(video_source, events=None)
    write_manifest(run_dir, "execution-1.json", video_source)
    write_events(run_dir, [])

    output_path = tmp_path / "rows.json"
    run_report(monkeypatch, run_dir, output_path)

    assert not output_path.exists()
    captured = capsys.readouterr().out
    assert "[WARN]" in captured
    assert "manifests_found=1 rows_produced=0 skipped_no_event_gt=1" in captured


def test_filters_events_by_threshold_for_same_video(tmp_path, monkeypatch):
    run_dir = tmp_path / "mae_20260817_120002"
    video_source = tmp_path / "data" / "inputs" / "same-video.MOV"
    write_ground_truth(
        video_source,
        events=[{"event_id": "gt-in", "direction": "IN", "t_sec": 10.0}],
    )
    write_manifest(
        run_dir,
        "execution-1.json",
        video_source,
        s_low=0.25,
        s_high=0.75,
        execution_id="execution-1",
        condition_key="condition-1",
    )
    write_manifest(
        run_dir,
        "execution-2.json",
        video_source,
        s_low=0.30,
        s_high=0.70,
        execution_id="execution-2",
        condition_key="condition-2",
    )
    write_events(
        run_dir,
        [
            event_row(
                s_low=0.25,
                s_high=0.75,
                video=video_source.name,
                event_id="pred-matching",
                timestamp_sec="10.0",
            ),
            event_row(
                s_low=0.30,
                s_high=0.70,
                video=video_source.name,
                event_id="pred-fp",
                timestamp_sec="40.0",
            ),
        ],
    )

    output_path = tmp_path / "rows.json"
    run_report(monkeypatch, run_dir, output_path)

    rows = json.loads(output_path.read_text(encoding="utf-8"))
    by_execution = {row["execution_id"]: row for row in rows}
    assert by_execution["execution-1"]["tp"] == 1
    assert by_execution["execution-1"]["fp"] == 0
    assert by_execution["execution-1"]["fn"] == 0
    assert by_execution["execution-2"]["tp"] == 0
    assert by_execution["execution-2"]["fp"] == 1
    assert by_execution["execution-2"]["fn"] == 1


def test_skips_empty_event_id_and_timestamp(tmp_path, monkeypatch):
    run_dir = tmp_path / "mae_20260817_120003"
    video_source = tmp_path / "data" / "inputs" / "invalid-rows.MOV"
    write_ground_truth(
        video_source,
        events=[{"event_id": "gt-in", "direction": "IN", "t_sec": 10.0}],
    )
    write_manifest(run_dir, "execution-1.json", video_source)
    write_events(
        run_dir,
        [
            event_row(video=video_source.name, event_id="", timestamp_sec="10.0"),
            event_row(video=video_source.name, event_id="pred-no-time", timestamp_sec=""),
            event_row(
                video=video_source.name,
                event_id="pred-invalid-time",
                timestamp_sec="not-a-number",
            ),
            event_row(video=video_source.name, event_id="pred-valid", timestamp_sec="10.0"),
        ],
    )

    output_path = tmp_path / "rows.json"
    run_report(monkeypatch, run_dir, output_path)

    rows = json.loads(output_path.read_text(encoding="utf-8"))
    assert rows[0]["tp"] == 1
    assert rows[0]["fp"] == 0
    assert rows[0]["fn"] == 0

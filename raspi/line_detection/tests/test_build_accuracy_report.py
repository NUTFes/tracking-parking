import json
import sys
from pathlib import Path


RASPI_ROOT = Path(__file__).parents[2]
LINE_ROOT = RASPI_ROOT / "line_detection"
sys.path.insert(0, str(LINE_ROOT))
sys.path.insert(0, str(RASPI_ROOT))

from build_accuracy_report import build_accuracy_report


def write_events_file(
    events_dir: Path,
    video_path: Path,
    *,
    filename: str,
    events: list[dict],
    wandb_run_id: str | None = None,
) -> Path:
    data = {
        "video_path": str(video_path),
        "events": events,
    }
    if wandb_run_id is not None:
        data["wandb_run_id"] = wandb_run_id
    path = events_dir / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_gt_file(
    video_path: Path,
    *,
    events: list[dict] | None = None,
    tolerance_sec: float = 0.5,
) -> Path:
    data = {
        "in": 1,
        "out": 1,
        "tolerance_sec": tolerance_sec,
    }
    if events is not None:
        data["events"] = events
    path = video_path.with_name(f"{video_path.stem}_gt.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_build_accuracy_report_writes_expected_row(tmp_path):
    events_dir = tmp_path / "logs"
    events_dir.mkdir()
    video_path = tmp_path / "videos" / "clip.MOV"
    write_gt_file(
        video_path,
        events=[
            {"event_id": "gt-in", "direction": "IN", "t_sec": 10.0},
            {"event_id": "gt-out", "direction": "OUT", "t_sec": 20.0},
        ],
    )
    write_events_file(
        events_dir,
        video_path,
        filename="events_clip.json",
        wandb_run_id="run-1",
        events=[
            {
                "track_id": 1,
                "event_type": "IN",
                "frame_id": 300,
                "timestamp_sec": 10.2,
                "confidence": "high",
                "line2_crossed": True,
                "event_id": "pred-in",
            },
            {
                "track_id": 2,
                "event_type": "OUT",
                "frame_id": 600,
                "timestamp_sec": 100.0,
                "confidence": "normal",
                "line2_crossed": True,
                "event_id": "pred-out",
            },
        ],
    )
    output_path = tmp_path / "report.json"

    rows, found, skipped = build_accuracy_report(events_dir, output_path)

    assert found == 1
    assert skipped == 0
    assert rows == [
        {
            "wandb_run_id": "run-1",
            "execution_id": None,
            "condition_key": None,
            "tp": 1,
            "fp": 1,
            "fn": 1,
            "precision": 0.5,
            "recall": 0.5,
            "f1": 0.5,
        }
    ]
    assert json.loads(output_path.read_text(encoding="utf-8")) == rows


def test_event_file_without_event_gt_is_skipped(tmp_path):
    events_dir = tmp_path / "logs"
    events_dir.mkdir()
    video_path = tmp_path / "videos" / "clip.MOV"
    write_gt_file(video_path)
    write_events_file(
        events_dir,
        video_path,
        filename="events_clip.json",
        events=[],
    )
    output_path = tmp_path / "report.json"

    rows, found, skipped = build_accuracy_report(events_dir, output_path)

    assert rows == []
    assert found == 1
    assert skipped == 1
    assert not output_path.exists()


def test_event_file_without_gt_is_skipped(tmp_path):
    events_dir = tmp_path / "logs"
    events_dir.mkdir()
    video_path = tmp_path / "videos" / "clip.MOV"
    write_events_file(
        events_dir,
        video_path,
        filename="events_clip.json",
        events=[],
    )
    output_path = tmp_path / "report.json"

    rows, found, skipped = build_accuracy_report(events_dir, output_path)

    assert rows == []
    assert found == 1
    assert skipped == 1
    assert not output_path.exists()


def test_multiple_event_files_produce_multiple_rows(tmp_path):
    events_dir = tmp_path / "logs"
    events_dir.mkdir()
    for index in range(2):
        video_path = tmp_path / "videos" / f"clip-{index}.MOV"
        write_gt_file(
            video_path,
            events=[
                {
                    "event_id": f"gt-{index}",
                    "direction": "IN",
                    "t_sec": float(index + 1),
                }
            ],
        )
        write_events_file(
            events_dir,
            video_path,
            filename=f"events_clip-{index}.json",
            wandb_run_id=f"run-{index}",
            events=[
                {
                    "track_id": index,
                    "event_type": "IN",
                    "frame_id": 30 * (index + 1),
                    "timestamp_sec": float(index + 1),
                    "confidence": "high",
                    "line2_crossed": True,
                    "event_id": f"pred-{index}",
                }
            ],
        )
    output_path = tmp_path / "report.json"

    rows, found, skipped = build_accuracy_report(events_dir, output_path)

    assert found == 2
    assert skipped == 0
    assert len(rows) == 2
    assert [row["wandb_run_id"] for row in rows] == ["run-0", "run-1"]
    assert json.loads(output_path.read_text(encoding="utf-8")) == rows

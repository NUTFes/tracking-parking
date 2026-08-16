"""Build event-accuracy rows from a multi-video threshold-sweep output."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))   # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[2]))   # raspi/（common 共有のため）

from common.event_matching import PredictedEvent
from common.ground_truth import load_ground_truth
from eval import build_event_accuracy_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build per-manifest event-accuracy rows from a multi-video sweep."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="mae_<timestamp> directory containing manifests/ and events.csv",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output .csv or .json path for the evaluation rows",
    )
    return parser.parse_args()


def load_event_rows(events_path: Path) -> list[dict[str, str]]:
    """Read the sweep's flat event CSV once for reuse across manifests."""
    with events_path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def matching_predicted_events(
    event_rows: list[dict[str, str]],
    *,
    video_name: str,
    s_low: float,
    s_high: float,
) -> list[PredictedEvent]:
    predicted = []
    for row in event_rows:
        if row.get("video") != video_name:
            continue

        try:
            row_s_low = float(row["s_low"])
            row_s_high = float(row["s_high"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isclose(row_s_low, s_low) or not math.isclose(row_s_high, s_high):
            continue

        event_id = (row.get("event_id") or "").strip()
        timestamp_raw = (row.get("timestamp_sec") or "").strip()
        if not event_id or not timestamp_raw:
            continue
        try:
            timestamp_sec = float(timestamp_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(timestamp_sec):
            continue

        predicted.append(
            PredictedEvent(
                event_id=event_id,
                direction=row.get("event_type", ""),
                t_sec=timestamp_sec,
            )
        )
    return predicted


def build_report_rows(run_dir: Path) -> tuple[list[dict], int, int, int]:
    """Build rows and return them with found/produced/skipped manifest counts."""
    manifest_paths = sorted((run_dir / "manifests").glob("*.json"))
    event_rows = load_event_rows(run_dir / "events.csv")
    rows = []
    skipped_no_event_gt = 0

    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config = manifest["config"]
        video_source = config["input_source"]
        s_low = float(config["s_low"])
        s_high = float(config["s_high"])
        gt = load_ground_truth(video_source)

        if not gt.events:
            skipped_no_event_gt += 1
            print(
                f"[WARN] {manifest_path.name}: no per-event GT for {video_source}; "
                "skipping manifest"
            )
            continue

        predicted = matching_predicted_events(
            event_rows,
            video_name=Path(video_source).name,
            s_low=s_low,
            s_high=s_high,
        )
        rows.append(
            build_event_accuracy_rows.build_eval_row(
                predicted,
                gt,
                wandb_run_id=manifest.get("wandb_run_id"),
                execution_id=manifest["execution_id"],
                condition_key=manifest["condition_key"],
            )
        )

    return rows, len(manifest_paths), len(rows), skipped_no_event_gt


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    rows, manifests_found, rows_produced, skipped_no_event_gt = build_report_rows(run_dir)

    if rows:
        output_path = build_event_accuracy_rows.write_eval_rows(rows, args.output)
        print(f"Wrote {rows_produced} evaluation rows to {output_path}")
    else:
        print("[WARN] No evaluation rows produced; output was not written")

    print(
        f"Summary: manifests_found={manifests_found} "
        f"rows_produced={rows_produced} "
        f"skipped_no_event_gt={skipped_no_event_gt}"
    )


if __name__ == "__main__":
    main()

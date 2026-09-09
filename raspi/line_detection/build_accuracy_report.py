#!/usr/bin/env python3
"""2ライン検知のイベントJSONからイベント精度評価行を作成する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1]))  # raspi/（common 共有のため）

from common.event_matching import PredictedEvent
from common.ground_truth import load_ground_truth
from eval import build_event_accuracy_rows


def collect_eval_rows(
    events_dir: str | Path,
) -> tuple[list[dict[str, Any]], int, int]:
    """イベントJSONを走査し、GT付き動画の評価行と件数を返す。"""
    event_paths = sorted(Path(events_dir).glob("events_*.json"))
    rows: list[dict[str, Any]] = []

    for events_path in event_paths:
        data = json.loads(events_path.read_text(encoding="utf-8"))
        predicted = [
            PredictedEvent(
                event_id=event["event_id"],
                direction=event["event_type"],
                t_sec=event["timestamp_sec"],
            )
            for event in data["events"]
        ]
        gt = load_ground_truth(data["video_path"])
        if not gt.events:
            print(
                f"[WARN] {events_path}: per-event GTが無いためスキップします"
            )
            continue

        rows.append(
            build_event_accuracy_rows.build_eval_row(
                predicted,
                gt,
                wandb_run_id=data.get("wandb_run_id"),
                execution_id=data.get("execution_id"),
                condition_key=data.get("condition_key"),
            )
        )

    found = len(event_paths)
    return rows, found, found - len(rows)


def build_accuracy_report(
    events_dir: str | Path,
    output_path: str | Path,
) -> tuple[list[dict[str, Any]], int, int]:
    """イベントJSONから評価行を作り、行があれば出力ファイルへ保存する。"""
    rows, found, skipped = collect_eval_rows(events_dir)
    if rows:
        build_event_accuracy_rows.write_eval_rows(rows, output_path)
    return rows, found, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="2ライン検知のイベントJSONからイベント精度評価行を作成する"
    )
    parser.add_argument(
        "--events-dir",
        default="data/outputs/logs",
        help="events_*.jsonがあるディレクトリ",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="評価行の出力先（.csv / .json）",
    )
    args = parser.parse_args(argv)

    rows, found, skipped = build_accuracy_report(args.events_dir, args.output)
    print(
        f"events_*.json: {found}件、評価行: {len(rows)}件、スキップ: {skipped}件"
    )
    if not rows:
        print("[WARN] 評価行が0件のため、何も書き出しませんでした")
    else:
        print(f"評価行を書き出しました: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

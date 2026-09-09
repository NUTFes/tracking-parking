"""GT・予測イベントからupdate_accuracy_from_sam3.py入力用の評価行を組み立てる。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Sequence

from common.event_matching import PredictedEvent, match_events
from common.ground_truth import GroundTruth


def build_eval_row(
    predicted: Sequence[PredictedEvent],
    gt: GroundTruth,
    *,
    wandb_run_id: str | None = None,
    execution_id: str | None = None,
    condition_key: str | None = None,
) -> dict[str, Any]:
    """予測イベントとGTを突合し、update_accuracy_from_sam3.py入力用の1行を返す。"""
    result = match_events(predicted, gt.events, gt.tolerance_sec)
    return {
        "wandb_run_id": wandb_run_id,
        "execution_id": execution_id,
        "condition_key": condition_key,
        "tp": result.tp,
        "fp": result.fp,
        "fn": result.fn,
        "precision": result.precision,
        "recall": result.recall,
        "f1": result.f1,
    }


def write_eval_rows(rows: Sequence[dict[str, Any]], output_path: str | Path) -> Path:
    """評価行をCSVまたはJSONへ書き出す（拡張子で判定）。update_accuracy_from_sam3.py --inputへそのまま渡せる形式。"""
    path = Path(output_path)
    if path.suffix not in (".json", ".csv"):
        raise ValueError(f"未対応の出力形式です: {path.suffix}（.csv / .json）")

    path.parent.mkdir(parents=True, exist_ok=True)

    if path.suffix == ".json":
        path.write_text(
            json.dumps(list(rows), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    fieldnames = [
        "wandb_run_id",
        "execution_id",
        "condition_key",
        "tp",
        "fp",
        "fn",
        "precision",
        "recall",
        "f1",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path

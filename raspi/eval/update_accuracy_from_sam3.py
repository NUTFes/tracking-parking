#!/usr/bin/env python3
"""
SAM3 の GT が揃った後に、既存 W&B run の summary に精度指標を後追い書き込むスクリプト（雛形）。

【実行と評価の分離】
本システムの計測スクリプト（02_run_analysis.py / 04_multi_video_mae.py / line_detection/main.py）は
速度・台数のみを即時記録し、精度系 summary キーは None で確保している。SAM3 の GT が揃った後に
本スクリプトを独立実行し、W&B API 経由で同一 run の summary を更新する（run の再開はしない）。

【GT の定義（重要）】
- 台数の最終 GT は人手の真値（既存 `*_gt.json`）を ground truth とする。
- SAM3 は per-vehicle 軌跡 / イベント列の生成補助に使い、SAM3 出力をそのまま GT としない。
- 評価単位（event / detection）は下記 EVAL_UNIT で選択。デフォルトは "event"。

使い方:
    # 書き込まずに対象 run と予定値だけ確認
    python update_accuracy_from_sam3.py --input eval_results.csv --dry-run
    # 実際に summary を更新
    python update_accuracy_from_sam3.py --input eval_results.csv
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))   # raspi/（common 共有のため）

# ── 設定 ────────────────────────────────────────────────────────────────────
WANDB_PROJECT_PATH = "tracking-parking"   # 例: "entity/project" or "project"
EVAL_UNIT = "event"                        # "event" or "detection"
GT_SOURCE = "sam3"

# 後追いで書き込む summary キー（計測時に None で確保済みのものと一致させる）
ACCURACY_KEYS = ["accuracy", "precision", "recall", "f1", "tp", "fp", "fn", "tn"]
# ────────────────────────────────────────────────────────────────────────────


class AmbiguousRunError(RuntimeError):
    """一意にrunを特定できず、誤更新を避けるため処理を止める場合の例外。"""


def load_eval_rows(input_path: Path) -> list[dict]:
    """SAM3 由来の評価結果テーブル（CSV / JSON）を読み込む。

    各行に per-run の accuracy/precision/recall/f1/tp/fp/fn/tn と、
    対応する `wandb_run_id`、`execution_id`、`condition_key` のいずれかを含める。
    旧データについては `exp_key` も利用できる。
    """
    if input_path.suffix == ".json":
        data = json.loads(input_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("rows", [])
    elif input_path.suffix == ".csv":
        import csv
        with open(input_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    else:
        raise ValueError(f"未対応の入力形式です: {input_path.suffix}（.csv / .json）")


def find_run(api, row: dict):
    """評価行に対応する W&B run を 1 つ特定する。

    優先順: wandb_run_id → execution_id → condition_key → 旧exp_key。
    config検索が複数一致した場合は候補を示す AmbiguousRunError を送出する。

    Returns:
        run or None（0件はWARNしてスキップ）
    """
    run_id = row.get("wandb_run_id")
    if run_id:
        try:
            return api.run(f"{WANDB_PROJECT_PATH}/{run_id}")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] wandb_run_id={run_id} の run を取得できません: {e}")
            return None

    search_candidates = (
        ("execution_id", row.get("execution_id")),
        ("condition_key", row.get("condition_key")),
        ("exp_key", row.get("exp_key")),
    )
    field, value = next(
        ((field, value) for field, value in search_candidates if value),
        (None, None),
    )
    if field is None:
        print(
            "[WARN] wandb_run_id / execution_id / condition_key / exp_key "
            "のいずれも無い行をスキップします"
        )
        return None

    runs = list(api.runs(WANDB_PROJECT_PATH, filters={f"config.{field}": value}))
    if len(runs) == 0:
        print(f"[WARN] {field}={value} に一致する run がありません。スキップします")
        return None
    if len(runs) > 1:
        candidates = ", ".join(
            f"{run.id} ({getattr(run, 'name', 'no-name')})" for run in runs
        )
        raise AmbiguousRunError(
            f"{field}={value} に複数runが一致しました: {candidates}"
        )
    return runs[0]


def build_summary_update(row: dict) -> dict:
    """評価行から summary へ書き込む値を組み立てる。"""
    update = {}
    for key in ACCURACY_KEYS:
        if key in row and row[key] not in (None, ""):
            update[key] = row[key]
    update["eval_unit"] = EVAL_UNIT
    update["gt_source"] = GT_SOURCE
    return update


def main() -> int:
    parser = argparse.ArgumentParser(description="SAM3 精度を既存 W&B run の summary へ後追い書き込む")
    parser.add_argument("--input", required=True, help="評価結果テーブル（.csv / .json）")
    parser.add_argument("--dry-run", action="store_true",
                        help="対象 run と書き込み予定値を表示するだけで書き込まない")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 入力ファイルが見つかりません: {input_path}")
        return 1

    rows = load_eval_rows(input_path)
    print(f"評価行数: {len(rows)}  dry_run={args.dry_run}")

    import wandb
    api = wandb.Api()

    updated = 0
    for row in rows:
        # TODO(GT 未整備): SAM3 出力から accuracy/precision/... を算出するマッチングロジック本体は
        #   GT データが揃ってから実装する。ここでは入力テーブルに算出済み値が入っている前提で
        #   run 特定 → summary 更新のインターフェースのみ確定させている。
        try:
            run = find_run(api, row)
        except AmbiguousRunError as exc:
            print(f"[ERROR] {exc}")
            print("誤ったrunへの書き込みを避けるため処理を停止します")
            return 2
        if run is None:
            continue

        update = build_summary_update(row)
        if args.dry_run:
            print(
                f"[DRY-RUN] run={run.id} "
                f"condition_key={row.get('condition_key')} → {update}"
            )
            continue

        run.summary.update(update)
        updated += 1
        print(f"[OK] run={run.id} summary を更新しました → {update}")

    if not args.dry_run:
        print(f"更新した run 数: {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

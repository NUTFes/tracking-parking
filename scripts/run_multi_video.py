#!/usr/bin/env python3
"""複数動画をrun_detection.pyで順に処理し、結果をサマリーへ集約する。

run_detection.pyは1動画ずつしか扱わないため、同条件での複数動画計測には
動画ごとの実行と結果の集約が要る。

**各runは独立したサブプロセスで走らせる。** 理由が2つある。

1. `load_dotenv` は既存の環境変数を上書きしない。同一プロセスで2つの.envを
   読むと後から読んだほうが無視されるため、画角ごとに設定を切り替えられない。
2. YOLOモデルとトラッカーの状態をrun間で持ち越さない。

閾値スイープは行わない。2ライン方式には探索対象のパラメータが無い。

対象動画の一覧は、動画と.envの対応を書いたJSONで与える（既定は
data/inputs/videos.json、`--videos` で変更可）。動画・.env・GTはいずれも
.gitignore対象のローカル資産のため、リポジトリには含まれない。
書式は data/inputs/videos.example.json を参照。

    [
      {"video": "data/inputs/sample_a.mp4", "env": "camera_a.env"},
      {"video": "data/inputs/sample_b.mp4", "env": "camera_b.env"}
    ]

.envは画角ごとに用意する。.env.templateをコピーし、画角ごとに
scripts/setup_lines.py でライン座標を設定すればよい。比較目的で走らせるときは、
比較条件（model/conf/iou/classes/imgsz/tracker/device/warmup）を全.envで揃えること。

出力:
    data/outputs/{EXP_NAME}/
    ├── {video_stem}/
    │   ├── logs/events_<timestamp>.json   # run_detection.pyが書く
    │   └── manifests/<execution_id>.json  # 同上
    └── summary.csv                        # 本スクリプトが集約する
"""
import argparse
import csv
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── パラメータ ──────────────────────────────────────────────────────────────
DEFAULT_VIDEO_LIST = "data/inputs/videos.json"

GT_DIR = os.getenv("GT_DIR", "data/inputs/configs")
EXP_NAME = os.getenv("EXP_NAME", "gate4_2line")

# comparison_keyの突合先。ROI方式は本リポジトリから削除済みのため既定では突合しない。
# 過去のROI方式runと比較したい場合のみ、そのrunディレクトリを渡す。
ROI_RUN_DIR = os.getenv("ROI_RUN_DIR", "")
# ────────────────────────────────────────────────────────────────────────────

SUMMARY_COLUMNS = (
    "video", "count_in", "gt_in", "count_out", "gt_out", "count_error",
    "high_confidence_events", "normal_confidence_events",
    "core_ms_p95", "end_to_end_ms_p95", "deadline_miss_rate",
    "wandb_run_id", "execution_id", "condition_key", "comparison_key",
)


def load_videos(list_path: str) -> list[tuple[str, str]]:
    """対象動画と.envの対応をJSONから読む。

    動画・.env・GTはいずれも.gitignore対象のローカル資産なので、
    リポジトリ内のハードコードではなく実行環境ごとのファイルで与える。
    """
    path = Path(list_path)
    if not path.exists():
        raise SystemExit(
            f"[ERROR] 動画リストがありません: {path}\n"
            f"  data/inputs/videos.example.json を {path} へコピーして編集してください。"
        )
    entries = json.loads(path.read_text(encoding="utf-8"))
    videos = []
    for i, entry in enumerate(entries):
        try:
            videos.append((entry["video"], entry["env"]))
        except (TypeError, KeyError) as exc:
            raise SystemExit(
                f"[ERROR] {path} の {i} 番目の要素に video/env がありません: {entry!r}"
            ) from exc
    if not videos:
        raise SystemExit(f"[ERROR] {path} に動画が1本もありません。")
    return videos


def gt_path_for(video: str) -> Path:
    """動画パスから対応するGTファイルのパスを導く。"""
    return Path(GT_DIR) / f"{Path(video).stem}_gt.json"


def check_inputs(videos: list[tuple[str, str]]) -> None:
    """動画・設定・GTの存在を先に確認する。

    1本目を数十分かけて処理した後に3本目のGTが無いと分かる、という失敗を避ける。
    """
    missing = []
    for video, env in videos:
        if not Path(video).exists():
            missing.append(f"動画がありません: {video}")
        if not Path(env).exists():
            missing.append(f"設定がありません: {env}")
        gt = gt_path_for(video)
        if not gt.exists():
            missing.append(f"GTがありません: {gt}")
    if missing:
        raise SystemExit("[ERROR] 実行前チェックに失敗しました:\n  " + "\n  ".join(missing))


def run_one(video: str, env: str, out_dir: Path) -> int:
    """run_detection.pyを1動画ぶん実行する。戻り値は終了コード。"""
    cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "run_detection.py"),
        "--input", video,
        "--env", env,
        "--gt", str(gt_path_for(video)),
        "--output", str(out_dir),
    ]
    print(f"\n{'=' * 70}\n実行: {Path(video).name}  (env={env})\n{'=' * 70}", flush=True)
    return subprocess.run(cmd).returncode


def latest_json(pattern: str) -> dict | None:
    paths = sorted(glob.glob(pattern))
    if not paths:
        return None
    return json.loads(Path(paths[-1]).read_text(encoding="utf-8"))


def collect(video: str, out_dir: Path) -> dict:
    """1runぶんの出力からサマリー行を組み立てる。"""
    events = latest_json(str(out_dir / "logs" / "events_*.json"))
    manifest = latest_json(str(out_dir / "manifests" / "*.json"))
    if events is None:
        return {"video": Path(video).name, "count_error": "収集失敗"}

    summary = events.get("summary", {})
    accuracy = events.get("accuracy", {})
    timing = events.get("timing", {})
    config = (manifest or {}).get("config", {})
    return {
        "video": Path(video).name,
        "count_in": summary.get("total_in"),
        "gt_in": accuracy.get("gt_in"),
        "count_out": summary.get("total_out"),
        "gt_out": accuracy.get("gt_out"),
        "count_error": accuracy.get("count_error"),
        "high_confidence_events": summary.get("high_confidence_events"),
        "normal_confidence_events": summary.get("normal_confidence_events"),
        "core_ms_p95": timing.get("core_ms_p95"),
        "end_to_end_ms_p95": timing.get("end_to_end_ms_p95"),
        "deadline_miss_rate": timing.get("deadline_miss_rate"),
        "wandb_run_id": events.get("wandb_run_id"),
        "execution_id": events.get("execution_id"),
        "condition_key": events.get("condition_key"),
        "comparison_key": config.get("comparison_key"),
    }


def roi_comparison_keys() -> dict:
    """ROI方式の確定runから、動画名ごとのcomparison_keyを読む。"""
    keys = {}
    for path in glob.glob(str(Path(ROI_RUN_DIR) / "manifests" / "*.json")):
        config = json.loads(Path(path).read_text(encoding="utf-8")).get("config", {})
        source = config.get("input_source")
        if source and config.get("comparison_key"):
            keys[Path(source).name] = config["comparison_key"]
    return keys


def print_summary(rows: list, summary_path: Path) -> None:
    print(f"\n{'=' * 74}\n集約結果\n{'=' * 74}")
    print(f"{'video':<26}{'IN':>10}{'OUT':>10}{'err':>6}{'high':>6}{'normal':>8}{'p95ms':>9}")
    total_error = 0
    for row in rows:
        err = row.get("count_error")
        if isinstance(err, int):
            total_error += err
        p95 = row.get("core_ms_p95")
        in_col = f"{row.get('count_in')}/{row.get('gt_in')}"
        out_col = f"{row.get('count_out')}/{row.get('gt_out')}"
        p95_col = f"{p95:.1f}" if isinstance(p95, (int, float)) else "-"
        print(
            f"{row['video']:<26}{in_col:>10}{out_col:>10}{str(err):>6}"
            f"{str(row.get('high_confidence_events')):>6}"
            f"{str(row.get('normal_confidence_events')):>8}{p95_col:>9}"
        )
    print(f"\n合計誤差: {total_error}   出力: {summary_path}")


def print_comparison_check(rows: list) -> None:
    """ROI方式のrunとcomparison_keyが一致するかを動画ごとに突合する。

    一致するrun同士でなければ速度値を方式間で直接比較できない、というのが
    comparison_keyの設計意図であるため、計測の直後に確認する。
    """
    roi_keys = roi_comparison_keys() if ROI_RUN_DIR else {}
    if not roi_keys:
        print("\n[INFO] ROI側のmanifestが無いため、comparison_keyの突合は行いません。")
        return

    print(f"\ncomparison_key の突合（対象: {ROI_RUN_DIR}）")
    mismatched = 0
    for row in rows:
        roi_key = roi_keys.get(row["video"])
        if roi_key is None:
            verdict = "ROI側に該当なし"
        elif roi_key == row.get("comparison_key"):
            verdict = "一致"
        else:
            verdict = "不一致"
            mismatched += 1
        print(f"  {row['video']:<26} {verdict}")
    if mismatched:
        print(f"\n[WARN] {mismatched}件でcomparison_keyが一致しません。"
              "速度値を方式間で直接比較できません。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="複数動画を順に処理し、比較用サマリーへ集約する"
    )
    parser.add_argument(
        "--videos",
        default=DEFAULT_VIDEO_LIST,
        help=f"動画と.envの対応を書いたJSON(既定: {DEFAULT_VIDEO_LIST})",
    )
    args = parser.parse_args()

    videos = load_videos(args.videos)
    check_inputs(videos)
    base = Path("data/outputs") / EXP_NAME
    base.mkdir(parents=True, exist_ok=True)
    print(f"動画数: {len(videos)}  出力先: {base}")

    rows, failed = [], []
    for video, env in videos:
        out_dir = base / Path(video).stem
        code = run_one(video, env, out_dir)
        if code != 0:
            failed.append(video)
            print(f"[ERROR] 異常終了（code={code}）: {video}", flush=True)
        rows.append(collect(video, out_dir))

    summary_path = base / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(SUMMARY_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in SUMMARY_COLUMNS})

    print_summary(rows, summary_path)
    print_comparison_check(rows)

    if failed:
        print(f"\n[ERROR] {len(failed)}本が異常終了: "
              + ", ".join(Path(v).name for v in failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""ROI方式と2ライン方式を動画ごとに交互実行し、同一セッション内の相対速度を測る。

docs.local/gate4-speed-comparison-caveat.html の結論（開発機での速度比較は
機体の熱状態に支配され、別々の時間帯に測った2つのrun同士では比較できない）
を受けた案1の実装。動画ごとにROI→2ライン→ROI→…と交互に呼ぶことで、熱状態の
上がり方を両方式へ均等にかけ、このrun内でのcore_ms_p95の比を相対比較として
読めるようにする。

ROI方式のコードは feat/mike/89-bbox-analysis-within-roi にしかなく、本ブランチの
worktreeには存在しない。そのため別ディレクトリにROI方式用のgit worktreeを用意し
（ROI_ROOT）、そちらのscripts/04_multi_video_mae.pyをサブプロセスから動画1本ぶんだけ
呼び出す（scripts/_gate4_single_video_runner.py、worktree内のみに存在するローカル
専用ブートストラップ。04_multi_video_mae.py自体は無変更）。2ライン方式はmain.pyを
run_multi_video.pyと同じ流儀でサブプロセス実行する。

各方式を独立サブプロセスにする理由はrun_multi_video.pyと同じ
（.envの上書き問題／YOLOモデルとトラッカーの状態をrun間で持ち越さないため）。

出力:
    data/outputs/{EXP_NAME}/
    ├── {video_stem}/                      # 2ライン方式（main.pyが書く）
    ├── timeline.csv                       # 交互実行の実施順・開始/終了時刻
    └── summary_alternating.csv            # 方式別の速度・精度を並べた集約
"""
import csv
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEOS = [
    ("data/inputs/1787008160.558032.mp4", "newcam.env"),
    ("data/inputs/1787009706.719727.mp4", "newcam.env"),
    ("data/inputs/1787011229.231516.mp4", "newcam.env"),
    ("data/inputs/1787012751.179971.mp4", "newcam.env"),
    ("data/inputs/1787014266.421887.mp4", "newcam.env"),
    ("data/inputs/IMG_2787.MOV", "img2787.env"),
]

GT_DIR = os.getenv("GT_DIR", "../roi-counter/data/inputs/configs")
EXP_NAME = os.getenv("EXP_NAME", "gate4_alt")

# ROI方式のコードが実際に存在するworktree（本ブランチには無い。docs.local/
# gate4-speed-comparison-caveat.htmlの案1採用にあたり `git worktree add` で作成）。
ROI_ROOT = Path(os.getenv(
    "ROI_ROOT", "/Users/ycn/Workspace/NUTMEG/tracking-parking-roi-mike",
))
ROI_DIR = ROI_ROOT / "raspi" / "roi-counter"
ROI_BOOTSTRAP = ROI_DIR / "scripts" / "_gate4_single_video_runner.py"

# ROI方式の確定run（exp_adopted_final_gtfix）と同じ採用値。
S_LOW = os.getenv("S_LOW", "0.26")
S_HIGH = os.getenv("S_HIGH", "0.32")
# ────────────────────────────────────────────────────────────────────────────

TIMELINE_COLUMNS = ("seq", "method", "video", "started_at", "ended_at", "duration_sec", "returncode")

SUMMARY_COLUMNS = (
    "video", "roi_count_in", "roi_gt_in", "roi_count_out", "roi_gt_out", "roi_count_error",
    "roi_core_ms_p95", "roi_comparison_key",
    "line_count_in", "line_gt_in", "line_count_out", "line_gt_out", "line_count_error",
    "line_core_ms_p95", "line_comparison_key",
    "speed_ratio_line_over_roi",
)


def gt_path_for(video: str) -> Path:
    return Path(GT_DIR) / f"{Path(video).stem}_gt.json"


def check_inputs() -> None:
    missing = []
    for video, env in VIDEOS:
        if not Path(video).exists():
            missing.append(f"動画がありません: {video}")
        if not Path(env).exists():
            missing.append(f"設定がありません: {env}")
        if not gt_path_for(video).exists():
            missing.append(f"GTがありません: {gt_path_for(video)}")
    if not ROI_BOOTSTRAP.exists():
        missing.append(
            f"ROI方式のブートストラップがありません: {ROI_BOOTSTRAP}\n"
            "  git worktree add でfeat/mike/89-bbox-analysis-within-roiを展開し、"
            "raspi/roi-counter/scripts/_gate4_single_video_runner.py を用意してください。"
        )
    if missing:
        raise SystemExit("[ERROR] 実行前チェックに失敗しました:\n  " + "\n  ".join(missing))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def run_logged(cmd: list, *, cwd: Path, env: dict, method: str, video: str, seq: int,
                timeline_rows: list) -> int:
    print(f"\n{'=' * 70}\n[{seq}] {method}: {Path(video).name}\n{'=' * 70}", flush=True)
    started = now_iso()
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(cwd), env=env)
    duration = time.monotonic() - t0
    ended = now_iso()
    timeline_rows.append({
        "seq": seq, "method": method, "video": Path(video).name,
        "started_at": started, "ended_at": ended,
        "duration_sec": round(duration, 1), "returncode": proc.returncode,
    })
    return proc.returncode


def run_roi_single(video: str, seq: int, timeline_rows: list) -> dict:
    roi_gt_config = (Path.cwd() / gt_path_for(video)).resolve()
    before = set(glob.glob(str(ROI_DIR / "data" / "outputs" / EXP_NAME / "mae_*")))

    env = os.environ.copy()
    env.update({
        "S_LOW_LIST": S_LOW,
        "S_HIGH_LIST": S_HIGH,
        "EXP_NAME": EXP_NAME,
        "USE_WANDB": "true",
        "WANDB_MODE": "offline",
        "WANDB_PROJECT": "tracking-parking",
        "WANDB_DIR": "data/outputs",
    })
    env.pop("YOLO_DEVICE", None)  # 確定runと同じくUltralyticsの自動選択に委ねる

    cmd = [sys.executable, str(ROI_BOOTSTRAP), "--gt-config", str(roi_gt_config)]
    code = run_logged(cmd, cwd=ROI_DIR, env=env, method="ROI", video=video, seq=seq,
                       timeline_rows=timeline_rows)
    if code != 0:
        print(f"[ERROR] ROI方式が異常終了（code={code}）: {video}", flush=True)
        return {"video": Path(video).name}

    after = set(glob.glob(str(ROI_DIR / "data" / "outputs" / EXP_NAME / "mae_*")))
    new_dirs = sorted(after - before)
    if not new_dirs:
        print(f"[ERROR] ROI方式の出力ディレクトリが見つかりません: {video}", flush=True)
        return {"video": Path(video).name}
    mae_dir = Path(new_dirs[-1])
    return collect_roi(video, mae_dir)


def collect_roi(video: str, mae_dir: Path) -> dict:
    manifest_paths = sorted(glob.glob(str(mae_dir / "manifests" / "*.json")))
    if not manifest_paths:
        return {"video": Path(video).name, "roi_count_error": "収集失敗"}
    manifest = json.loads(Path(manifest_paths[-1]).read_text(encoding="utf-8"))
    config = manifest.get("config", {})

    results_csv = mae_dir / "results.csv"
    row = {}
    if results_csv.exists():
        df = pd.read_csv(results_csv)
        if not df.empty:
            row = df.iloc[-1].to_dict()

    core_ms_p95 = None
    timing_path = mae_dir / "gate4_timing_summary.json"
    if timing_path.exists():
        timing_summary = json.loads(timing_path.read_text(encoding="utf-8"))
        core_ms_p95 = timing_summary.get("core_ms_p95")

    return {
        "video": Path(video).name,
        "roi_count_in": row.get("count_in"),
        "roi_gt_in": row.get("gt_in"),
        "roi_count_out": row.get("count_out"),
        "roi_gt_out": row.get("gt_out"),
        "roi_count_error": row.get("count_error"),
        "roi_core_ms_p95": core_ms_p95,
        "roi_comparison_key": config.get("comparison_key"),
    }


def run_line_single(video: str, env_file: str, seq: int, timeline_rows: list) -> dict:
    out_dir = Path("data/outputs") / EXP_NAME / Path(video).stem
    cmd = [
        sys.executable, "main.py",
        "--input", video,
        "--env", env_file,
        "--gt", str(gt_path_for(video)),
        "--output", str(out_dir),
    ]
    code = run_logged(cmd, cwd=Path.cwd(), env=os.environ.copy(), method="2ライン",
                       video=video, seq=seq, timeline_rows=timeline_rows)
    if code != 0:
        print(f"[ERROR] 2ライン方式が異常終了（code={code}）: {video}", flush=True)
    return collect_line(video, out_dir)


def latest_json(pattern: str) -> dict | None:
    paths = sorted(glob.glob(pattern))
    if not paths:
        return None
    return json.loads(Path(paths[-1]).read_text(encoding="utf-8"))


def collect_line(video: str, out_dir: Path) -> dict:
    events = latest_json(str(out_dir / "logs" / "events_*.json"))
    manifest = latest_json(str(out_dir / "manifests" / "*.json"))
    if events is None:
        return {"video": Path(video).name, "line_count_error": "収集失敗"}

    summary = events.get("summary", {})
    accuracy = events.get("accuracy", {})
    timing = events.get("timing", {})
    config = (manifest or {}).get("config", {})
    return {
        "video": Path(video).name,
        "line_count_in": summary.get("total_in"),
        "line_gt_in": accuracy.get("gt_in"),
        "line_count_out": summary.get("total_out"),
        "line_gt_out": accuracy.get("gt_out"),
        "line_count_error": accuracy.get("count_error"),
        "line_core_ms_p95": timing.get("core_ms_p95"),
        "line_comparison_key": config.get("comparison_key"),
    }


def print_summary(rows: list) -> None:
    print(f"\n{'=' * 90}\n交互実行 集約結果\n{'=' * 90}")
    header = f"{'video':<24}{'ROI p95':>10}{'2line p95':>11}{'比(2line/ROI)':>16}{'ROI err':>9}{'2line err':>11}"
    print(header)
    for row in rows:
        roi_p95 = row.get("roi_core_ms_p95")
        line_p95 = row.get("line_core_ms_p95")
        ratio = row.get("speed_ratio_line_over_roi")
        roi_p95_s = f"{roi_p95:.1f}" if isinstance(roi_p95, (int, float)) else "-"
        line_p95_s = f"{line_p95:.1f}" if isinstance(line_p95, (int, float)) else "-"
        ratio_s = f"{ratio:.2f}x" if isinstance(ratio, (int, float)) else "-"
        print(
            f"{row['video']:<24}{roi_p95_s:>10}{line_p95_s:>11}{ratio_s:>16}"
            f"{str(row.get('roi_count_error')):>9}{str(row.get('line_count_error')):>11}"
        )


def main() -> int:
    check_inputs()
    base = Path("data/outputs") / EXP_NAME
    base.mkdir(parents=True, exist_ok=True)
    (ROI_DIR / "data" / "outputs" / EXP_NAME).mkdir(parents=True, exist_ok=True)
    print(f"動画数: {len(VIDEOS)}  出力先(2ライン): {base}  出力先(ROI): "
          f"{ROI_DIR / 'data' / 'outputs' / EXP_NAME}")

    timeline_rows: list = []
    rows: list = []
    seq = 0
    for video, env_file in VIDEOS:
        seq += 1
        roi_result = run_roi_single(video, seq, timeline_rows)
        seq += 1
        line_result = run_line_single(video, env_file, seq, timeline_rows)

        merged = {**roi_result, **{k: v for k, v in line_result.items() if k != "video"}}
        roi_p95 = merged.get("roi_core_ms_p95")
        line_p95 = merged.get("line_core_ms_p95")
        if isinstance(roi_p95, (int, float)) and isinstance(line_p95, (int, float)) and roi_p95 > 0:
            merged["speed_ratio_line_over_roi"] = line_p95 / roi_p95
        rows.append(merged)

        # 動画ごとに逐次書き込み（数時間かかるrunなので、失敗時も途中結果を失わない）。
        timeline_path = base / "timeline.csv"
        with timeline_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(TIMELINE_COLUMNS))
            writer.writeheader()
            writer.writerows(timeline_rows)

        summary_path = base / "summary_alternating.csv"
        with summary_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(SUMMARY_COLUMNS))
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k) for k in SUMMARY_COLUMNS})

    print_summary(rows)
    print(f"\n出力: {base / 'summary_alternating.csv'}  {base / 'timeline.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

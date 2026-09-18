#!/usr/bin/env bash
# 本番実行（カメラ入力 → 検知 → API送信 → 録画）。
#
# ライン設定（GUI）は初回だけの作業で、ここには含めない。
# 先に scripts/setup_production_lines.sh を実行しておくこと。
#
# 使い方:
#   scripts/run_production.sh                      # 既定の設定で実行
#   DETECT_ENV=other.env scripts/run_production.sh  # 検知設定を差し替える
#   scripts/run_production.sh --no-api              # 送信だけ止める（引数はそのまま渡る）
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
DETECT_ENV="${DETECT_ENV:-jetson-newcam.env}"
API_ENV="${API_ENV:-jetson-production.env}"
CAMERA="${CAMERA:-0}"
LOG_DIR="${LOG_DIR:-data/outputs}"

for path in "$PYTHON" "$DETECT_ENV" "$API_ENV"; do
  if [[ ! -e "$path" ]]; then
    echo "エラー: $path が見つかりません" >&2
    exit 1
  fi
done

# API設定はプロセス環境へ入れる。run_detection.py の --env は指定ファイルだけを
# 読むため、API_* をこちらで export しないと送信が有効にならない。
set -a
# shellcheck disable=SC1090
. "./$API_ENV"
set +a

echo "=== 事前チェック ==="
"$PYTHON" scripts/preflight.py --camera "$CAMERA" --env "$DETECT_ENV"

LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$LOG_DIR"

echo
echo "=== 実行 ==="
echo "ログ: $LOG_FILE"
echo "停止は Ctrl+C（SIGINT）。kill -9 は書きかけのセグメントが再生不能になる"
echo

# -u を付けるのは、パイプへ流すと出力がバッファに溜まり、落ちたときに
# 何も残らないため。
exec "$PYTHON" -u scripts/run_detection.py \
  --camera "$CAMERA" --env "$DETECT_ENV" "$@" 2>&1 | tee -a "$LOG_FILE"

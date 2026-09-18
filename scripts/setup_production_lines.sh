#!/usr/bin/env bash
# 設置カメラの画角でライン座標を設定する（初回・画角を変えたときだけ）。
#
# GUIウィンドウでマウス操作が要るため、本番実行のスクリプトとは分けている。
# ここで設定した座標は検知ループが使う解像度に紐づくので、同じ.envを渡して
# 同じ CAMERA_WIDTH / CAMERA_HEIGHT / CAMERA_FOURCC でフレームを掴む。
#
# 使い方:
#   scripts/setup_production_lines.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
DETECT_ENV="${DETECT_ENV:-jetson-newcam.env}"
CAMERA="${CAMERA:-0}"

for path in "$PYTHON" "$DETECT_ENV"; do
  if [[ ! -e "$path" ]]; then
    echo "エラー: $path が見つかりません" >&2
    exit 1
  fi
done

if [[ -z "${DISPLAY:-}" ]]; then
  echo "エラー: DISPLAY が未設定です。GUIを開けません" >&2
  echo "  リモートから実行する場合は、画面転送のあるセッション上で実行してください" >&2
  exit 1
fi

echo "カメラ${CAMERA}のフレーム上で5点をクリックしてください。"
echo "  Line1 始点 → Line1 終点 → Line2 始点 → Line2 終点 → 駐車場基準点"
echo "  r: やり直し / q または ウィンドウを閉じる: 終了"
echo "設定は $DETECT_ENV へ保存されます（他のキーは変更しません）。"
echo

"$PYTHON" scripts/setup_lines.py --camera "$CAMERA" --env "$DETECT_ENV"

echo
echo "=== 保存された座標を確認 ==="
grep -E "^(LINE1_|LINE2_|PARKING_REF_)" "$DETECT_ENV"

echo
echo "続いて事前チェックで画角との整合を確認します"
"$PYTHON" scripts/preflight.py --camera "$CAMERA" --env "$DETECT_ENV" || true

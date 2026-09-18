# 当日の実行手順（エッジ機）

設置済みの Jetson を当日動かすための手順。上から順に実行する。

仕組みの説明は [README](../README.md#本番実行エッジ機) にある。ここは**当日その場で
見る用**に、順序と判断基準だけを書く。

2026-09-18 に本番APIへ向けた通し実行（2時間49分・イベント104件）を行い、全工程を
踏んだうえで書いた。数値はそのときの実測。

## 当日の流れ

| # | 工程 | 所要 | 頻度 |
|---|---|---|---|
| 1 | 画角とライン座標の確認 | 5〜10分 | 画角を変えたときだけ |
| 2 | `system_count` の初期化 | 5分 | **毎回** |
| 3 | 起動 | 1分 | 毎回 |
| 4 | 稼働中の監視 | 随時 | 毎回 |
| 5 | 終了 | 1分 | 毎回 |

**2 を飛ばさないこと。** 初期値が実態とずれるとカウントが静かに狂い、デバイス側では
直せない。詳細は [docs/system-count-operation.md](system-count-operation.md)。

## 0. 開始前の確認

```bash
cd ~/workspace/tracking-parking
git status                          # 作業ツリーがクリーンか
ls -l /dev/video0                   # カメラが見えているか
df -h .                             # 空き容量（実測 約12GB/日）
```

**カメラは1プロセスしか開けない。** 前回の実行が残っていないか必ず見る。

```bash
fuser -v /dev/video0                # 何も出なければ空き
pgrep -af "python.*run_detection"   # 残っていれば後述の手順で止める
```

## 1. 画角とライン座標（画角を変えたときだけ）

カメラを動かしたらライン座標は**必ず設定し直す**。座標は設定時の画角に紐づくため、
画角が変わると通路でも駐車マスでもない場所に線が残る。

```bash
scripts/setup_production_lines.sh
```

GUIが開くので5点をクリックする。

```
Line1 始点 → Line1 終点 → Line2 始点 → Line2 終点 → 駐車場基準点
r: やり直し / q または ウィンドウを閉じる: 終了
```

- Line1 は**入口側**、Line2 は**駐車場側**。この順に横切ると入庫、逆が出庫
- 駐車場基準点は**駐車場の内側**に置く。これがどちら側を駐車場とみなすかを決める
- 線分は**有限**。車が実際に通る範囲をカバーしていないと交差と判定されない

終了後に事前チェックが走り、座標が画角の内側にあるかを確認する。

## 2. `system_count` の初期化（毎回）

実際の駐車台数を数えて、<https://admin-trapa.nutfes.net> から合わせる。

| 状況 | 操作 |
|---|---|
| 朝イチ・台数0から | `reset-all` に `target: "system"`（0固定・全駐車場） |
| 途中から開始 | 個別リセットに `count: <実測台数>`, `target: "system"` |

`target` を `"current"` にすると公開ビューアの表示が書き換わるので注意。

反映を確認する（認証不要）。

```bash
curl -s https://api-trapa.nutfes.net/api/v1/parking-lots | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d if isinstance(d, list) else d.get('items', d.get('data', []))
for r in rows:
    if r.get('has_device'):
        print(f\"id={r.get('id')} {r.get('name')}: \"
              f\"current={r.get('current_count')} system={r.get('system_count')}\")
"
```

Jetson が紐づくのは **`講義棟北` (id=3)**。

## 3. 起動

```bash
scripts/run_production.sh
```

事前チェックが通ると実行に入る。この表示が出ていることを確認する。

```
=== 事前チェック ===
  カメラ0: 1280x720
  API送信: 有効 → https://api-trapa.nutfes.net/api/v1
  録画: 有効 / 256MBごと / 空きXXXGB

事前チェック: 問題なし
```

**「API送信: 無効」と出たら送信されない。** `jetson-production.env` の
`API_ENABLED` と `DEVICE_API_KEY` を見る。

録画を有効にするには `SAVE_VIDEO=true` を渡す（`jetson-newcam.env` は比較条件を
固定してあるファイルなので、書き換えずに環境変数で上書きする）。

```bash
SAVE_VIDEO=true scripts/run_production.sh
```

送信だけ止めたいとき（動作確認など）は `--no-api` を付ける。

```bash
scripts/run_production.sh --no-api
```

## 4. 稼働中の監視

ログは `data/outputs/run_YYYYMMDD_HHMMSS.log`。

```bash
# 検知イベント
grep -E "^\[Frame " data/outputs/run_*.log | tail -5

# 入出庫の内訳
grep -E "^\[Frame " data/outputs/run_*.log | grep -oE " (IN|OUT) " | sort | uniq -c

# エラー
grep -iE "traceback|error|失敗|例外" data/outputs/run_*.log
```

**最優先で見るのはスプール。**

```bash
wc -l < data/outputs/unsent_events.jsonl   # ファイルが無ければ0件
```

溜まっていれば送信先に到達できていない。**検知と録画は止まらない**ので、慌てて
プロセスを落とさないこと。イベントは保全され、次回起動時に再送される
（`request_id` でべき等なので二重計上しない）。

参考値（2026-09-18 実測、1280x720 / yolov8s / Orin NX）:

| 指標 | 実測 |
|---|---|
| スループット | 8.0 fps（約101ms/フレーム） |
| GPU使用率 | 81〜94% |
| 温度 | tj 56℃ |
| 消費電力 | VDD_IN 約7.3W |
| 録画容量 | 約12GB/日（256MBで分割） |

## 5. 終了

**SIGINT（Ctrl+C）で止める。** `kill -9` は書きかけの録画セグメントが再生不能になる。

前面で動かしているなら Ctrl+C。バックグラウンドなら PID を指定する。

```bash
pgrep -af "python.*run_detection"                    # 実体のPIDを確認
kill -INT <PID>
```

**`pgrep` はシェルのラッパープロセスも拾う。** `.venv/bin/python -u scripts/run_detection.py`
の行を選ぶこと。ラッパーを止めても Python は生き残り、カメラを掴んだままになる
（次回の起動が `can't open camera by index` で落ちる）。

正常に止まるとこう出る。

```
停止要求を受け付けました。現在のフレームを処理してから終了します（もう一度Ctrl+Cで即時終了）
ユーザーによる中断
処理完了!
✓ JSONログを保存: .../logs/events_YYYYMMDD_HHMMSS.json
✓ CSVログを保存: .../logs/events_YYYYMMDD_HHMMSS.csv
============================================================
処理結果サマリー
入庫: N / 出庫: N / 現在駐車台数: N
============================================================
```

## 6. 終了後の確認

```bash
pgrep -af "python.*run_detection" | grep -v "bash -c"   # 残っていないこと
fuser -v /dev/video0                                     # カメラが解放されたこと
ls -la data/outputs/logs/ | tail -3                      # JSON/CSVが出たこと
ls -la data/outputs/videos/camera_*/                     # 全セグメントが確定したこと
wc -l < data/outputs/unsent_events.jsonl 2>/dev/null     # 未送信が残っていないこと
```

**スプールが残っていたら次回起動時に再送される。** 消さないこと。

## トラブル対応

### 送信先へ到達できない

```
[api] ハートビート送信に失敗しました: ... timed out
```

検知と録画は継続する。イベントはスプールへ退避され、次回起動時に再送される。
**実行を止める必要はない。** 送信先が復旧しても復旧ログは出ない（送信成功は無言）
ので、確認するなら直接叩く。

```bash
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 \
  https://api-trapa.nutfes.net/api/v1/health
```

### カメラが開けない

```
[ WARN:0@3.554] global cap_v4l.cpp:914 open VIDEOIO(V4L2:/dev/video0): can't open camera by index
エラー: 動画を開けません: 0
```

ほぼ前回のプロセスが残っている。`fuser -v /dev/video0` で掴んでいる PID を特定して
`kill -INT` する。

### 録画中のmp4が読めない

```
moov atom not found
```

インデックスはセグメント確定時に書かれるため、書き込み中のファイルからは
フレームを取り出せない。確定済みの1つ前のセグメントを使う。

### system_count が 0 から動かない

出庫が入庫を上回り、0で下限クランプされている。初期値が実際の駐車台数より
小さかったことが原因。admin でリセットして合わせ直す
（[docs/system-count-operation.md](system-count-operation.md)）。

## 関連

- [README](../README.md#本番実行エッジ機) — 仕組みと設定キー
- [docs/system-count-operation.md](system-count-operation.md) — `system_count` の初期化
- [docs/decisions/0003-camera-input-and-recording.md](decisions/0003-camera-input-and-recording.md) — カメラ入力と録画の設計
- [docs/decisions/0002-api-event-delivery.md](decisions/0002-api-event-delivery.md) — 送信方式

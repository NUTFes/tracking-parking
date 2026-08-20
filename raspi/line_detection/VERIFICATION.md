# 2ライン方式 検証手順

2ライン検知ロジックが期待どおり動くことを、実動画1本に対して端から端まで確認する手順。
新しい環境で動かすとき、判定ロジックを変更したとき、ROI方式と比較するときに使う。

対象ブランチ: `experiment/ucn/two-lines-detection`
対象ディレクトリ: `raspi/line_detection/`

ROI方式の検証手順は `raspi/roi-counter/VERIFICATION.md`（`feat/mike/89-bbox-analysis-within-roi`）にある。

## 0. 前提条件

- リポジトリルートで `uv sync` 済みであること
- 実動画がローカルに存在すること。`data/` は `.gitignore` 対象なので、
  リポジトリを新しく取得した環境では別途配置が必要
  - `data/inputs/IMG_2787.MOV`
  - GT（正解台数）は ROI方式と共有する: `../roi-counter/data/inputs/configs/IMG_2787_gt.json`
- `.env` が存在すること（`.gitignore` 対象。無ければ 2章で作成する）
- 1回の実行に数分〜十数分かかる（YOLO推論を含むため）

以降のコマンドは断りがない限り `raspi/line_detection/` をカレントディレクトリとして書く。

### W&B（実験記録）について

速度比較（6章）は `WANDB_MODE=offline` で実行する。**オフライン記録はW&Bへの
ログイン無しで動く**（ローカルに run ディレクトリが作られるだけ）。

W&Bサーバへ実際にアップロードするには、事前にログインが必要。

```bash
wandb login          # 初回のみ。ブラウザでAPIキーを取得して貼り付ける
```

ログイン状態は次で確認できる。

```bash
grep -q "api.wandb.ai" ~/.netrc && echo "ログイン済み" || echo "未ログイン"
```

未ログインのままでも検証手順そのものは完走する。ただし**offline runはローカルに
溜まり続けるだけで、W&B上では一切参照できない**。manifestに記録される
`wandb_run_id` も、同期するまではW&B上に対応する実体が無い点に注意すること。

> **`WANDB_DIR=data/outputs` を省略しないこと。** `raspi/common/wandb_logger.py` の
> `wandb.init()` は `dir` を渡していないため、未指定だとwandbが**カレントディレクトリ直下**に
> `wandb/` を作る。`data/` の外に出るとgitignoreの対象外になり、run一式を失いやすい
> （ROI方式で実際に一度失っている）。

## 1. ユニットテスト

実データを流す前に、純ロジックが壊れていないことを確認する。
リポジトリルートから実行する。

```bash
uv run pytest raspi/ -q
```

**合格基準**: 全件パス（2026-08-20 時点で 161 passed）。

`raspi/common/` は ROI方式とbyte-identicalで共有しているため、ここを変更した場合は
ROI方式側のテストも実行すること。

## 2. ライン座標の設定

`.env` が無い場合、または画角が変わった場合はGUIで設定し直す。

```bash
uv run python line_setup/setup_lines.py --video data/inputs/IMG_2787.MOV
```

動画の先頭フレームが表示されるので、次の5点をこの順にクリックする。

1. Line1 始点（入口側）
2. Line1 終点（入口側）
3. Line2 始点（駐車場側）
4. Line2 終点（駐車場側）
5. 駐車場基準点（駐車場内の任意の点）

`r` キーでやり直し、`q` キーまたはウィンドウを閉じると保存される。

> **注意**: このツールは `.env` を**丸ごと上書きする**。`MODEL_PATH` や `MARGIN_PX` など
> ライン座標以外の値もテンプレートの既定値で書き戻されるため、実行後に `.env` を開いて
> 意図した値になっているか確認すること。

`.env` を手で作る場合は `.env.template` をコピーして `MODEL_PATH` を実在するモデルへ
書き換える（テンプレートはfine-tuned modelを指しているが、手元に無ければ `yolov8s.pt` でよい）。

## 3. ライン配置の目視確認

実行前に、設定したラインが意図した位置にあるかを確認する。
引数は位置指定で `<動画パス> [出力動画パス] [開始フレーム] [終了フレーム]`（既定は 0〜300フレーム）。

```bash
uv run python visualize_lines_and_vehicles.py data/inputs/IMG_2787.MOV
```

出力動画として残す場合、およびフレーム範囲を変える場合:

```bash
uv run python visualize_lines_and_vehicles.py data/inputs/IMG_2787.MOV debug_vis.mp4 300 600
```

起動時に `Line1` / `Line2` / `駐車場基準点` / `MARGIN_PX` の値が標準出力に表示される。
これらが `.env` の意図した値になっていること、そして描画されたラインが路面上の
意図した位置にあることを目視で確かめる。

## 4. 本実行（GT比較あり）

```bash
uv run python main.py \
  --input data/inputs/IMG_2787.MOV \
  --gt ../roi-counter/data/inputs/configs/IMG_2787_gt.json
```

**確認する項目**: 実行中に `GT比較: count_error=0 (in=0, out=0)` が出たあと、
末尾に次のサマリーが表示される。

```
============================================================
処理結果サマリー
============================================================
入庫: 22
出庫: 0
現在駐車台数: 22
高信頼度イベント: <N>
通常信頼度イベント: <N>
平均処理時間: <X.XX>ms/frame
============================================================
```

- `入庫: 22` / `出庫: 0` がGT（`IMG_2787_gt.json` の `in`/`out`）と一致すること
- `GT比較: count_error=0` であること
- `高信頼度イベント` と `通常信頼度イベント` が両方とも1件以上あること
  （Line2通過によるconfidence確定が機能していることの確認）

`--gt` を省略すると `<動画名>_gt.json` を入力動画と同じディレクトリから自動探索する。
見つからなければ警告のみでGT比較なしのまま続行する。`--gt` で明示指定したパスが
存在しない場合は起動時にエラーで停止する。

## 5. 出力の確認

イベントログJSONの整合性を確認する。

```bash
python3 -c "
import json, glob
path = sorted(glob.glob('data/outputs/logs/events_*.json'))[-1]
data = json.load(open(path))
ids = [e['event_id'] for e in data['events']]
print('file:', path)
print('events:', len(ids), '/ unique event_id:', len(set(ids)))
print('high  :', sum(e['confidence'] == 'high' for e in data['events']))
print('normal:', sum(e['confidence'] == 'normal' for e in data['events']))
print('count_error:', data.get('accuracy', {}).get('count_error'))
"
```

**合格基準**: `events` の件数と `unique event_id` の件数が一致すること（イベントIDの重複が無い）。

`data/outputs/` には他に次が生成される。

| パス | 内容 |
|---|---|
| `logs/events_<timestamp>.json` | イベント列・summary・timing・run識別子・GT比較結果 |
| `logs/events_<timestamp>.csv` | 同内容のCSV |
| `videos/annotated_<動画名>.mp4` | 可視化済み動画（`SAVE_VIDEO=true` 時） |
| `manifests/<execution_id>.json` | run識別子・再現情報・出力パスの相互参照 |

## 6. ROI方式との速度比較

比較可能なrunにするには、両方式で動画・モデル・classes・confidence・IoU・image size・
tracker・device・warm-up・動画保存/表示設定を揃える必要がある。
これらから生成される `comparison_key` が一致するrun同士だけを直接比較する。

```bash
VEHICLE_CLASSES=2,7 CONFIDENCE_THRESHOLD=0.25 IOU_THRESHOLD=0.7 \
SAVE_VIDEO=false SHOW_DISPLAY=false SAVE_LOGS=true \
YOLO_DEVICE=cpu YOLO_IMGSZ=640 YOLO_TRACKER=botsort.yaml WARMUP_FRAMES=30 \
EXP_DEVICE_NAME=raspi5 EXP_DEVICE_ACCELERATOR=cpu \
USE_WANDB=true WANDB_MODE=offline WANDB_DIR=data/outputs \
uv run python main.py \
  --input data/inputs/IMG_2787.MOV \
  --gt ../roi-counter/data/inputs/configs/IMG_2787_gt.json \
  --wandb --device-name raspi5
```

> **注意**: 手元の `.env` は比較条件と異なる値（`CONFIDENCE_THRESHOLD=0.5`、
> `VEHICLE_CLASSES=2,3,5,7`、`IOU_THRESHOLD=0.3` など）になっていることがある。
> 比較目的で実行するときは、上記のように**環境変数で明示的に上書きする**こと。
> `.env.template` 側は比較条件に揃えてある。

速度指標は timing schema v2 に従い `read_ms` / `inference_tracking_ms` /
`counting_logic_ms` / `core_ms` / `output_ms` / `end_to_end_ms` に分割される。
方式比較には warm-up 除外後の `core_ms_p95`、実機のリアルタイム判定には
`end_to_end_ms` と `deadline_miss_rate` を使う。

`comparison_key` の一致確認:

```bash
python3 -c "
import json, glob
p = sorted(glob.glob('data/outputs/manifests/*.json'))[-1]
c = json.load(open(p))['config']
print('comparison_key:', c['comparison_key'])
print('condition_key :', c['condition_key'])
print('git_dirty     :', c['git_dirty'])
"
```

**合格基準**: `git_dirty` が `false` であること（作業ツリーが汚れた状態で計測していない）。

offline run は後日アップロードできる（`wandb login` 済みであること。0章参照）。

```bash
wandb sync data/outputs/wandb/offline-run-<timestamp>-<run_id>
```

同期していない run は、manifest に `wandb_run_id` が記録されていてもW&B上には存在しない。
区切りのよいところでまとめて同期しておくこと。

## 7. イベント単位の精度評価

台数（`count_error`）ではなく、個々のイベントがGTと時刻レベルで対応するかを評価する。

```bash
uv run python build_accuracy_report.py \
  --events-dir data/outputs/logs \
  --output data/outputs/event_accuracy.csv
```

> **前提**: この評価にはGT JSONに `events` 配列（`event_id` / `direction` / `t_sec`）が
> 必要になる。現在の `IMG_2787_gt.json` は台数（`in`/`out`）のみで `events` を持たないため、
> このコマンドは `[WARN] per-event GTが無いためスキップします` を出して評価行0件で終わる。
> **これは現時点では正常な挙動**。イベント単位のアノテーションを作成してから使う。

## 8. 合格基準のまとめ

| 確認項目 | 合格基準 |
|---|---|
| ユニットテスト | 全件パス |
| 本実行の台数 | `入庫: 22　出庫: 0`、`count_error=0` |
| confidence | high / normal とも1件以上 |
| `event_id` | 出力JSON内で重複なし |
| `git_dirty` | `false`（速度計測を行う場合） |

## 9. この手順で確認できないこと

- **イベント単位の精度（precision / recall / F1）**。GTにイベント単位のアノテーションが
  未整備のため（7章参照）
- **`tolerance_sec`（既定10.0秒）と `MAX_FRAME_GAP`（既定90フレーム）の妥当性**。
  実データによる分布計測が必要
- **実機（Raspberry Pi）でのリアルタイム性**。開発機での計測値は参考値にとどまる。
  `EXP_DEVICE_NAME` / `EXP_DEVICE_ACCELERATOR` を実機の値にして計測し直すこと

## 10. 関連資料

- `README.md` — システム構成、設定パラメータ、アルゴリズムの解説
- `docs/wandb_integration_spec_v2.md` — 実験記録の仕様
- `raspi/roi-counter/VERIFICATION.md` — ROI方式の検証手順（別ブランチ）

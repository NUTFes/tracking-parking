# ROI方式 検証手順

ROIカウントロジックが期待どおり動くことを、実動画1本に対して端から端まで確認する手順。
新しい環境で動かすとき、判定ロジックを変更したとき、設置のたびにROIを引き直すときに使う。

対象ブランチ: `feat/mike/89-bbox-analysis-within-roi`
対象ディレクトリ: `raspi/roi-counter/`

2ライン方式の検証手順は `raspi/line_detection/VERIFICATION.md`（`experiment/ucn/two-lines-detection`）にある。

## 0. 前提条件

- リポジトリルートで `uv sync` 済みであること
- 実動画とGT設定JSONがローカルに存在すること。`data/` は `.gitignore` 対象なので、
  リポジトリを新しく取得した環境では別途配置が必要
  - `data/inputs/IMG_2787.MOV`
  - `data/inputs/configs/IMG_2787_gt.json`
- YOLOモデル（`yolov8s.pt`）。未配置なら初回実行時に自動ダウンロードされる
- 動画1本の検出パスに数分かかる（5分・9023フレームで約5〜10分）

以降のコマンドは断りがない限り `raspi/roi-counter/` をカレントディレクトリとして書く。

### 進行度方式について

進行度 `s` の計算方式は `PROGRESS_METHOD` で切り替わる。**既定は `edge_distance`**。

| 方式 | 内容 | 画角が変わったとき |
|---|---|---|
| `edge_distance`（既定） | ROIの4頂点を単位正方形へ写す射影変換のv座標 | ROIを同じ物理目印に引き直せば閾値をそのまま使える |
| `y_normalized` | ROI全体のy範囲で線形正規化 | ROI形状に依存するため閾値の移植性が無い |

過去の記録（`phase3f_final` 等）と比較する場合は `PROGRESS_METHOD=y_normalized` を
明示すること。`condition_key` に方式名が含まれるため、方式が違うrunは同一条件とみなされない。

## 1. ユニットテスト

実データを流す前に、純ロジックが壊れていないことを確認する。
リポジトリルートから実行する。

```bash
uv run pytest raspi/ -q
```

**合格基準**: 全件パス（2026-08-20 時点で 264 passed）。

`raspi/common/` は2ライン方式とbyte-identicalで共有しているため、ここを変更した場合は
2ライン方式側のテストも実行すること。

## 2. ROI 4頂点の設定

設置のたび、または画角が変わったときにGUIで引き直す。

```bash
uv run python roi_setup/setup_roi.py \
  --config data/inputs/configs/IMG_2787_gt.json \
  --seek-sec 5
```

**頂点は必ず 奥側左 → 奥側右 → 入口側右 → 入口側左 の順にクリックする。**
この順序は `src/progress.py` の `calc_s_edge_distance` が要求するもので、
間違えると透視変換が壊れる。

| 操作 | キー |
|---|---|
| 前後にシーク | `.` / `,`（1秒）、`]` / `[`（10秒） |
| フレーム再取得（カメラ入力ではこれのみ） | `space` |
| 直前の点を取り消し / 全リセット | `u` / `r` |
| 表示方式の切り替え（表示のみ） | `m` |
| グリッド表示 | `g` |
| **保存** | `s` |
| 保存せず終了 | `q` |

**確認する項目**:

- 車両が写っていないフレームを選ぶこと（車体の特徴点は次回には存在しない）
- 4頂点は路面の物理的な目印（白線の端、縁石、車止め）に合わせること。
  これが `edge_distance` の画角非依存性の前提になる
- 4点そろった時点で赤字のエラーが出ていないこと（巻き方向の誤り、自己交差、退化を検出する）
- `s_low` / `s_high` のバンド線が、台形ROIに対して遠近に沿って**傾いて**描かれること
  （水平線になる場合は `y_normalized` 表示になっている）

> **注意**: このツールが編集するのは**ROI4頂点だけ**。`s_low` / `s_high` は設定JSONから
> 読んで表示するのみで、書き込まない。閾値はスイープの検証結果に従うべきもので、
> 手動決定の対象ではないため。

保存すると次の2つが更新される。

- `data/inputs/reference_frames/{stem}_{timestamp}.png` — ROI線を焼き込まないクリーンな参照フレーム
- 設定JSONの `roi` と `roi_setup` キーのみ（`in`/`out`/`events` 等は保持）

同じ状態でもう一度 `s` を押すと「変更がないため保存をスキップしました」と出る（冪等ガード）。

## 3. ROI配置の確認

```bash
uv run python scripts/01_show_roi.py \
  --config data/inputs/configs/IMG_2787_gt.json
```

起動時に `src/roi.check_roi_geometry` による妥当性検証が走り、エラーがあれば
動画を開く前に終了する。`data/outputs/roi_check.png` に描画結果が保存される。

方式を変えて比較する場合:

```bash
uv run python scripts/01_show_roi.py \
  --config data/inputs/configs/IMG_2787_gt.json \
  --progress-method y_normalized
```

> **用語の区別**: `data/outputs/roi_check.png` は確認用の**描画済み**画像。
> `data/inputs/reference_frames/*.png` は層2（将来のホモグラフィ追従）が使う
> **クリーンな**参照フレーム。別物なので混同しないこと。

## 4. 閾値スイープ（s_low / s_high の決定）

GT付き動画に対して閾値の組み合わせを総当たりし、MAE（count_error）を算出する。

```bash
ls data/inputs/configs/          # 対象JSONを目視確認（意図しないファイルの混入がないか）

USE_WANDB=true WANDB_MODE=offline WANDB_PROJECT=tracking-parking \
  EXP_NAME=exp_edge_distance_sweep \
  uv run python scripts/04_multi_video_mae.py
```

起動直後に `動画数: N  パラメータ組み合わせ: M` が出る。既定グリッドは
`S_LOW_LIST` 9値 × `S_HIGH_LIST` 9値 = 81通り。

**検出パスは動画1本につき1回だけ**実行され、閾値の組み合わせごとには軽量な
カウントロジックの再生だけが走る（`build_detection_trace` / `replay_counts`）。
そのため組み合わせ数を増やしても、増えるのは再生コストのみ。

範囲を絞る場合は環境変数で上書きする。

```bash
S_LOW_LIST=0.15,0.20,0.25 S_HIGH_LIST=0.40,0.45,0.50 \
  EXP_NAME=verification uv run python scripts/04_multi_video_mae.py
```

> **注意**: `s_low >= s_high` になる組み合わせが1つでも含まれると、起動時に
> `ValueError` で停止する（不正な条件で計測しないための設計）。

**出力**: `data/outputs/{EXP_NAME}/mae_{timestamp}/`

| ファイル | 内容 |
|---|---|
| `mae_summary.csv` | パラメータごとのMAEサマリー（`s_low, s_high, mae, mean_elapsed_ms`） |
| `results.csv` | 動画 × パラメータごとの詳細 |
| `events.csv` | 全run分の確定イベント |
| `manifests/{execution_id}.json` | run識別子・再現情報 |
| `diagnostics/{execution_id}.{json,csv}` | IN_CANDIDATE停滞trackの診断 |

実行末尾に `MAE最小: s_low=X s_high=Y mae=Z` が表示される。

### 閾値の選び方

**MAE最小の値をそのまま採るのではなく、同点集合の形を見ること。**

MAE=0になる組み合わせは複数存在することが多い。その中から選ぶ基準は次の2つ。

1. **同点集合の中央付近を選ぶ。** 境界に近い閾値は、トラッキングのわずかな揺らぎで
   結果が変わりやすく頑健性が低い
2. **MAE=0が探索範囲の端にしか現れていない場合は、範囲を広げて再検証する。**
   崖の位置が分からないまま端の値を採用してはいけない

実際、初回のスイープでは `s_high=0.55`（探索範囲の下端）でしかMAE=0が出ず、
`s_high=0.60` で急にMAE=4へ悪化する崖状の分布だった。範囲を `0.20` まで広げて
再検証したところ `s_high=0.20〜0.55` の全域でMAE=0と判明し、崖から十分離れた
`s_high=0.45` を採用した（選定の詳細は `README.md` の「s_low/s_high 書き戻し履歴」）。

## 5. 選定した閾値の書き戻し

閾値を設定JSONへ**手動で**書き込む。GUIは書き込まない設計のため、専用ツールは無い。

`data/inputs/configs/IMG_2787_gt.json` のトップレベルへ `s_low` / `s_high` を追加する
（`video` / `roi` / `in` / `out` / `roi_setup` は変更しない）。

```json
{
  "video": "data/inputs/IMG_2787.MOV",
  "roi": [[690, 430], [1310, 430], [1550, 660], [484, 638]],
  "in": 22,
  "out": 0,
  "s_low": 0.2,
  "s_high": 0.45,
  "roi_setup": { ... }
}
```

書き戻したらJSON構文を確認する。

```bash
python3 -c "import json; json.load(open('data/inputs/configs/IMG_2787_gt.json')); print('JSON構文OK')"
```

`main.py` と `01_show_roi.py` は `load_roi_config` 経由でこのJSONを読むため、
書き戻し後は追加のコード変更なしに新しい閾値が反映される。

> **トレーサビリティ**: `data/` はgit管理外なので、この編集はgit履歴に残らない。
> **選定根拠（該当 `execution_id` / `wandb_run_id` / `condition_key` / `git_sha`）は
> `README.md` の「s_low/s_high 書き戻し履歴」節へ追記すること。**
> これがgit管理下で参照できる唯一の記録になる。

## 6. 本実行

```bash
uv run python main.py --config data/inputs/configs/IMG_2787_gt.json
```

`q` キーで終了。末尾に `入庫: N  出庫: N` が表示される。

**合格基準**: 書き戻した閾値でGT（`in=22`, `out=0`）と一致すること。

## 7. 1動画の詳細分析（任意）

軌跡・処理時間・アノテーション動画が必要なときに使う。

```bash
uv run python scripts/02_run_analysis.py
```

> **注意**: このスクリプトは `VIDEO_SOURCE` / `ROI_POINTS` / `S_LOW` / `S_HIGH` が
> **スクリプト先頭にハードコード**されており、設定JSONを読まない（実験時に手で値を
> 振る用途のため意図的に据え置いている）。使う場合は 45〜60行目付近を直接編集すること。
> `03_sweep_params.py` も同様。

## 8. イベント単位の精度評価

台数（`count_error`）ではなく、個々のイベントがGTと時刻レベルで対応するかを評価する。

```bash
uv run python scripts/05_build_accuracy_report.py \
  --run-dir data/outputs/exp_edge_distance_sweep/mae_<timestamp> \
  --output data/outputs/event_accuracy.csv
```

> **前提**: この評価にはGT JSONに `events` 配列（`event_id` / `direction` / `t_sec`）が
> 必要になる。現在の `IMG_2787_gt.json` は台数（`in`/`out`）のみで `events` を持たないため、
> 該当動画はスキップされる。**これは現時点では正常な挙動**。イベント単位の
> アノテーションを作成してから使う。

## 9. 合格基準のまとめ

| 確認項目 | 合格基準 |
|---|---|
| ユニットテスト | 全件パス |
| ROI設定（GUI） | 幾何エラーなし、バンド線が遠近に沿って傾く |
| ROI配置確認 | `check_roi_geometry` がエラーを出さない |
| 閾値スイープ | 選定値で `mae=0`、かつ同点集合の境界でないこと |
| 本実行 | `入庫: 22　出庫: 0`（GTと一致） |
| 書き戻し | JSON構文OK、`load_roi_config` が新しい値を返す |
| トレーサビリティ | README に選定根拠を追記済み |

## 10. この手順で確認できないこと

- **OUT方向の閾値妥当性**。GT付き動画が `IMG_2787`（`in=22, out=0`）の1本のみで、
  OUT方向のイベントが1件も含まれていない。OUT方向を含むGTが手に入り次第、再検証が必要
- **イベント単位の精度（precision / recall / F1）**。GTにイベント単位のアノテーションが
  未整備のため（8章参照）
- **複数動画にわたる汎化**。現在のMAEは実質1動画の count_error と同じ
- **実機（Raspberry Pi）でのリアルタイム性**。開発機での計測値は参考値にとどまる
- **`main.py` の長時間安定性**。`counter.cleanup()` を呼んでいないため、24/7運用では
  stale trackが蓄積しうる（`README.md` の「既知の問題」参照）

## 11. 関連資料

- `README.md` — ディレクトリ構造、設定JSONのスキーマ、`condition_key` への影響、
  s_low/s_high 書き戻し履歴、既知の問題
- `raspi/line_detection/VERIFICATION.md` — 2ライン方式の検証手順（別ブランチ）

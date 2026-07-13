# roi-counter

ROI内を通過する車両の進行度 `s` を用いて入庫・出庫を判定するカウントシステム．

## ディレクトリ構造

```
roi-counter/
├── src/                    # コアモジュール
│   ├── roi.py              # ROI判定・y範囲取得
│   ├── progress.py         # 進行度 s の計算
│   ├── tracker.py          # 車両状態データクラス
│   ├── tracker_lifecycle.py # run間のYOLO tracker状態初期化
│   ├── counter.py          # 状態機械・入出庫カウント
│   └── visualizer.py       # フレーム描画
├── scripts/
│   ├── 00_convert_fps.py   # FPS変換
│   ├── 01_show_roi.py      # ROI確認（静止フレーム）
│   ├── 02_run_analysis.py  # 1動画の詳細分析
│   ├── 03_sweep_params.py  # 1動画 × 閾値スイープ
│   └── 04_multi_video_mae.py  # 複数動画 × 閾値 → MAE
├── analysis/
│   └── 01_visualize_threshold_sweep.py  # スイープ結果の可視化
├── tests/                  # ユニットテスト
└── main.py                 # 本番推論
```

## パラメータ（各スクリプト先頭でハードコード）

| パラメータ | 説明 |
|---|---|
| `VIDEO_SOURCE` | 動画ファイルパスまたはカメラインデックス（`0` 等） |
| `ROI_POINTS` | ROIの4頂点（画素座標，左上から時計回り） |
| `S_LOW` | 入口側バンドの上限（`s < S_LOW` → 入口側） |
| `S_HIGH` | 奥側バンドの下限（`s > S_HIGH` → 奥側） |
| `VEHICLE_CLASSES` | 検出対象クラス（COCO: `2`=car, `7`=truck） |

## scripts/ 各スクリプトの用途と入力

### 00_convert_fps.py
指定動画のFPSを落として同ディレクトリに `{stem}_fixed{ext}` で出力する．

**入力**: `VIDEO_SOURCE`（動画ファイルパス）

---

### 01_show_roi.py
動画の指定秒数地点のフレームにグリッド・ROI・バンドラインを描画して確認する．

**入力**: `VIDEO_SOURCE`，`ROI_POINTS`，`S_LOW`，`S_HIGH`

**出力**: `data/outputs/roi_check.png`

---

### 02_run_analysis.py
1動画を処理し，車両ごとの軌跡・フレームごとの処理時間・アノテーション動画を出力する．

**入力**: `VIDEO_SOURCE`，`ROI_POINTS`，`S_LOW`，`S_HIGH`

**出力**: `data/outputs/{EXP_NAME}/{stem}_{timestamp}/`
```
├── result.json     # カウント結果・処理時間サマリー
├── vehicles.csv    # track_id ごとの s_history・状態
├── frames.csv      # フレームごとの処理時間
├── annotated.mp4   # 可視化済み動画（SAVE_VIDEO=true時）
└── run_manifest.json # run識別子・再現情報・出力パス
```

`frames.csv` は timing schema v2 に従い、`read_ms`、`inference_tracking_ms`、
`counting_logic_ms`、`core_ms`、`output_ms`、`end_to_end_ms` を保存する。
`core_ms_p95` を方式比較、`end_to_end_ms` と `deadline_miss_rate` を実機の
リアルタイム判定に使う。先頭 `WARMUP_FRAMES`（既定30）は処理自体には含めるが、
速度 summary から除外する。

主な速度比較用環境変数:

```bash
WARMUP_FRAMES=30 YOLO_IMGSZ=640 YOLO_TRACKER=botsort.yaml \
SAVE_VIDEO=false SHOW_DISPLAY=false USE_WANDB=true \
WANDB_MODE=offline python scripts/02_run_analysis.py
```

比較する2方式では、入力動画・モデル・vehicle classes・confidence・IoU・image size・
tracker・device・warm-up・動画保存/表示設定を一致させる。これらから生成した
`comparison_key` が同じ W&B run だけを直接比較する。offline run は後日
`wandb sync <run_dir>` でアップロードできる。

各runでは用途の異なる識別子を分離する。

- `condition_key`: ROI、閾値、動画・モデルhash、tracker設定、Git・主要ライブラリ版など、
  結果へ影響する条件の型付きcanonical JSONから生成するSHA-256。条件が同じ再実行では同じ値になる。
- `execution_id`: 実行開始時に生成するUUID。同条件を再実行しても必ず別の値になる。
- `wandb_run_id`: W&Bが発行するID（`USE_WANDB=true`時のみ）。
- `display_name`: W&B UI向けの可読名。一意性の判定には使わない。

`exp_key` は移行期間中のみ `condition_key` のaliasとして保存する。新規の突合では
`wandb_run_id`、`execution_id`、`condition_key` の順で使用する。
`run_manifest.json`はW&Bの有効・無効にかかわらず保存し、上記ID、W&B config、
ローカル出力の絶対パスを相互参照できるようにする。

---

### 03_sweep_params.py
1動画に対して `S_LOW_RANGE × S_HIGH_RANGE` の全組み合わせを実行し，Count Error を記録する．

**入力**:
- `VIDEO_SOURCE`（動画ファイルパス）
- `GT_PATH`（グランドトゥルース JSON）またはファイル名から自動導出（`{stem}_gt.json`）
- `ROI_POINTS`，`S_LOW_RANGE`，`S_HIGH_RANGE`

**GT JSONフォーマット**（`data/inputs/{stem}_gt.json`）:
```json
{"in": 29, "out": 2}
```

**出力**: `data/outputs/{EXP_NAME}/sweep_{timestamp}/results.csv`
```
s_low, s_high, count_in, count_out, gt_in, gt_out, count_error, elapsed_ms, mean_frame_ms, max_frame_ms, tracker_reset, tracker_reset_method, ultralytics_version
```

各閾値runの直前にYOLO trackerを初期化し、前runのtrack IDや追跡状態を
持ち越さない。`tracker.reset()`を利用できない場合はモデルを再生成し、それも
失敗した場合は独立性を保証できないため評価を中断する。

`tracker_reset_method`には、初回のclean状態を表す`clean_start`、trackerの
`reset()`を実行した`tracker_reset`、モデルを再生成した`model_reload`のいずれかを
記録する。`ultralytics_version`と併せて、各runの初期化方法を追跡できる。

---

### 04_multi_video_mae.py
複数動画にわたって `S_LOW_LIST × S_HIGH_LIST` の組み合わせを実行し，MAEを算出する．

**入力**: `GT_DIR` 配下の設定 JSON（1動画につき1ファイル）

**設定 JSONフォーマット**（`data/inputs/configs/{name}.json`）:
```json
{
  "video": "data/movies/IMG_2788_fixed.MOV",
  "roi": [[630, 770], [1270, 770], [1530, 1000], [390, 1000]],
  "in": 29,
  "out": 2
}
```

**出力**: `data/outputs/{EXP_NAME}/mae_{timestamp}/`
```
├── results.csv      # 動画 × パラメータごとの詳細
├── mae_summary.csv  # パラメータごとのMAEサマリー
└── manifests/       # 動画 × パラメータrunごとのmanifest（execution_id.json）
```

`results.csv`には`tracker_reset`、`tracker_reset_method`、`ultralytics_version`も
記録する。`03_sweep_params.py`と同じ共通処理を使い、動画・閾値の各runを独立させる。
`USE_WANDB=true`の場合は`wandb_run_id`、`execution_id`、`condition_key`と互換用
`exp_key`も記録する。W&Bを無効にした場合も`manifests/`には各runの識別子と
再現情報が残る。

tracker初期化処理はUltralyticsの内部APIに依存するため、依存バージョンは
`8.4.72`に固定している。バージョン更新時は`test_tracker_lifecycle.py`を含む
ROI counterのテストを実行すること。

---

## analysis/

### 01_visualize_threshold_sweep.py
`03_sweep_params.py` の `results.csv` を読み込んでヒートマップとラインプロットを生成する．

**入力**: `SWEEP_CSV`（`results.csv` のパス）

**出力**: 同ディレクトリに `heatmap_count_error.png`，`line_s_low.png`，`line_s_high.png`，`heatmap_elapsed_ms.png`

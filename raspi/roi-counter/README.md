# roi-counter

ROI内を通過する車両の進行度 `s` を用いて入庫・出庫を判定するカウントシステム．

## ディレクトリ構造

```
roi-counter/
├── src/                    # コアモジュール
│   ├── roi.py              # ROI判定・y範囲取得・頂点順序と凸性の検証
│   ├── roi_config.py       # 設定JSON（roi/roi_setup）の読み書き
│   ├── progress.py         # 進行度 s の計算方式とレジストリ・等s線の幾何
│   ├── progress_diagnostics.py # s_max診断集計
│   ├── tracker.py          # 車両状態データクラス
│   ├── tracker_lifecycle.py # run間のYOLO tracker状態初期化
│   ├── counter.py          # 状態機械・入出庫カウント
│   └── visualizer.py       # フレーム描画
├── roi_setup/
│   └── setup_roi.py        # GUIでROI4頂点を手動決定するツール
├── scripts/
│   ├── 00_convert_fps.py   # FPS変換
│   ├── 01_show_roi.py      # ROI確認（静止フレーム、設定JSON読み込み）
│   ├── 02_run_analysis.py  # 1動画の詳細分析（ROIハードコード）
│   ├── 03_sweep_params.py  # 1動画 × 閾値スイープ（ROIハードコード）
│   └── 04_multi_video_mae.py  # 複数動画 × 閾値 → MAE（設定JSON読み込み）
├── analysis/
│   └── 01_visualize_threshold_sweep.py  # スイープ結果の可視化
├── tests/                  # ユニットテスト
└── main.py                 # 本番推論（設定JSON読み込み）
```

## パラメータ

ROIとその周辺の値は、スクリプトによって設定JSON経由とハードコードの2通りがある。

| スクリプト | ROI・s_low/s_highの出所 |
|---|---|
| `roi_setup/setup_roi.py`、`main.py`、`scripts/01_show_roi.py` | **設定JSON**（`--config`。既定`data/inputs/configs/IMG_2787_gt.json`） |
| `scripts/02_run_analysis.py`、`scripts/03_sweep_params.py` | **ハードコード**（スクリプト先頭。実験時に手で値を振る用途のため据え置き） |
| `scripts/04_multi_video_mae.py` | **設定JSON**（`GT_DIR`配下の複数ファイル） |

`main.py`・`01_show_roi.py`・`04_multi_video_mae.py`が同じ設定JSONを読むため、
GUIで決めたROIはこの3本すべてに反映される（`02`/`03`は対象外。ハードコードされた
値を手で書き換える必要がある）。

設定JSONの外にある、スクリプト先頭ハードコードのパラメータ:

| パラメータ | 説明 |
|---|---|
| `VIDEO_SOURCE` | （`02`/`03`のみ）動画ファイルパスまたはカメラインデックス（`0` 等） |
| `ROI_POINTS` | （`02`/`03`のみ）ROIの4頂点（画素座標） |
| `S_LOW` / `S_HIGH` | （`02`/`03`のみ）入口側/奥側バンドの閾値 |
| `CLEANUP_THRESHOLD` | 未更新trackを削除またはarchiveへ移すまでのフレーム数（既定150） |
| `MAX_CANDIDATE_AGE` | 候補状態を維持する最大フレーム数（既定300） |
| `S_HISTORY_LIMIT` | trackごとに保持する`s_history`の最大件数（既定300、0は無制限） |
| `PROGRESS_METHOD` | 進行度計算方式（`y_normalized`または`edge_distance`、既定`edge_distance`）。環境変数でも指定可能 |
| `VEHICLE_CLASSES` | 検出対象クラス（COCO: `2`=car, `7`=truck） |

ROIの4頂点は「奥側左、奥側右、入口側右、入口側左」の順序で指定する。
`y_normalized`は従来どおりROI全体のy範囲で正規化し、`edge_distance`は入口辺から奥辺への
透視変換距離で正規化する。既定方式は`edge_distance`である（画角非依存性を優先。
ROIを路面の同じ物理目印に打ち直せば、画角が変わる設置のたびに`s_low`/`s_high`を
再検証しなくて済む。過去の`y_normalized`運用と比較する場合は
`PROGRESS_METHOD=y_normalized`を明示指定する）。

## roi_setup/setup_roi.py — ROI4頂点の手動決定

画角は検証時のものとは限らず、微小に変化しうる。そのたびに`04_multi_video_mae.py`の
ようなスイープスクリプトを回すのは非現実的なため、ROIの4頂点だけは
`line_detection/line_setup/setup_lines.py`と同様にGUIで手動決定する。

```bash
uv run python roi_setup/setup_roi.py --config data/inputs/configs/IMG_2787_gt.json
```

**このツールが編集するのはROI4頂点だけ**。`s_low`/`s_high`は設定JSONから読んで
確認表示するのみで、書き込まない。無次元の進行度閾値はROI形状に依存しないので、
ROIを同じ物理領域（路面の白線の端・縁石・車止めなど）に打ち直せば、画角が変わっても
`s_low`/`s_high`はスイープで検証した値のまま使い続けられる、という設計方針による。

**操作**: 動画/カメラの1フレームを表示し、奥側左→奥側右→入口側右→入口側左の順で
4点をクリックする（既存の点はドラッグで移動可）。`.`/`,`で1秒、`]`/`[`で10秒シークでき
（カメラ入力では無効、`space`キーで再取得）、`m`で表示方式（y_normalized/edge_distance）
をトグルできる（表示のみ）。4点そろうと頂点の順序・凸性を検証し、エラーは赤、警告は
黄でオーバーレイする。`s`キーで明示的に保存する（ウィンドウを閉じるだけでは保存しない）。

**保存されるもの**:
- クリーンな参照フレーム（ROI線等を焼き込んでいない生のフレーム）を
  `data/inputs/reference_frames/{video_stem}_{timestamp}.png`として保存する。
  `01_show_roi.py`が出す`data/outputs/roi_check.png`（確認用・描画済み）とは別物。
- 設定JSONの`roi`と`roi_setup`キーだけを更新する。`in`/`out`/`events`/
  `tolerance_sec`・未知キーはそのまま保持する。

**設定JSONの`roi_setup`スキーマ**:
```json
{
  "video": "data/inputs/IMG_2787.MOV",
  "roi": [[690, 430], [1310, 430], [1550, 660], [500, 660]],
  "in": 22,
  "out": 0,
  "roi_setup": {
    "schema_version": 1,
    "vertex_order": ["far_left", "far_right", "near_right", "near_left"],
    "coordinate_space": "pixel",
    "frame_width": 1920,
    "frame_height": 1080,
    "baseline_roi": [[690, 430], [1310, 430], [1550, 660], [500, 660]],
    "reference_frame": {
      "path": "data/inputs/reference_frames/IMG_2787_20260819_213011.png",
      "sha256": "…",
      "source": "data/inputs/IMG_2787.MOV",
      "source_type": "file",
      "source_sha256": "…",
      "frame_index": 150,
      "position_sec": 5.004
    },
    "set_at": "2026-08-19T21:30:11+09:00",
    "set_by": "ycn",
    "tool": "roi_setup/setup_roi.py"
  }
}
```

`baseline_roi`は人が打った原本を保持する予約フィールド。将来ホモグラフィによる
画角の自動追従（層2）を足す場合、そのランタイム出力は`roi_alignment`という
兄弟トップレベルキーに置く想定で、`roi_setup`（人間とこのツールだけが書く）とは
書き手を分離する。`roi`は常に「いま使うROI」を指すので、層2を追加しても
`main.py`・`01_show_roi.py`・`04_multi_video_mae.py`側の読み込みコードは
変更不要になる。現時点では`roi_alignment`は未実装。

**`condition_key`への影響**: `roi_setup`の追加はJSONファイル全体のバイト列を
変えるため、`common.ground_truth.GroundTruth.sha256`（ひいては
`04_multi_video_mae.py`が生成する`condition_key`）が変わる。これは
`roi_points`が既に`condition_key`の入力に含まれている以上、ROIの再設定という
条件変更に伴う想定内の挙動であり、避けるべきものではない。ROIを動かしていない
状態で保存を繰り返しても`roi_setup`が既に付与済みなら書き込み自体をスキップする
（`src.roi_config.roi_points_changed`）ため、無意味な`set_at`更新でkeyが
動くことはない。過去runと比較する場合は`roi_points`と`s_low`/`s_high`を
手で突き合わせること。

## scripts/ 各スクリプトの用途と入力

### 00_convert_fps.py
指定動画のFPSを落として同ディレクトリに `{stem}_fixed{ext}` で出力する．

**入力**: `VIDEO_SOURCE`（動画ファイルパス）

---

### 01_show_roi.py
動画の指定秒数地点のフレームにグリッド・ROI・バンドラインを描画して確認する．

**入力**: `--config`（設定JSON。既定`data/inputs/configs/IMG_2787_gt.json`）、
`--seek-sec`、`--progress-method`（既定は環境変数`PROGRESS_METHOD`、
未設定なら`edge_distance`）

**出力**: `data/outputs/roi_check.png`（`--output`で変更可。確認用・描画済み画像。
`roi_setup/setup_roi.py`が保存するクリーンな参照フレームとは別物）

起動時に`src.roi.check_roi_geometry`でROIの妥当性を検証し、エラー/警告を
標準出力に表示する（頂点順序の誤りなどを動画を開く前に検出できる）。

---

### 02_run_analysis.py
1動画を処理し，車両ごとの軌跡・フレームごとの処理時間・アノテーション動画を出力する．

**入力**: `VIDEO_SOURCE`，`ROI_POINTS`，`S_LOW`，`S_HIGH`

**出力**: `data/outputs/{EXP_NAME}/{stem}_{timestamp}/`
```
├── result.json     # カウント結果・処理時間サマリー
├── vehicles.csv    # track_id ごとの s_history・状態
├── events.csv      # カウント確定イベント列（track_id・方向・確定フレーム）
├── frames.csv      # フレームごとの処理時間
├── annotated.mp4   # 可視化済み動画（SAVE_VIDEO=true時）
└── run_manifest.json # run識別子・再現情報・出力パス
```

`events.csv` は `track_id, event_type, frame_index, timestamp_sec, is_warmup` を
持つ。`event_type` は `IN`/`OUT`、`frame_index` はカウントが確定したフレーム番号、
`timestamp_sec` はそのフレームの相対経過秒（fpsが不明な場合は空）。
**warm-up中に確定したイベントも除外しない**（`is_warmup` 列で明示するのみ）。
除外すると行数が `count_in + count_out` と一致しなくなるため。

`frames.csv` は timing schema v2 に従い、`read_ms`、`inference_tracking_ms`、
`counting_logic_ms`、`core_ms`、`output_ms`、`end_to_end_ms` を保存する。
`core_ms_p95` を方式比較、`end_to_end_ms` と `deadline_miss_rate` を実機の
リアルタイム判定に使う。先頭 `WARMUP_FRAMES`（既定30）は処理自体には含めるが、
速度 summary から除外する。

既定の`edge_distance`は、台形や回転したROIでも入口辺から奥辺への進行度を計算する
（画角非依存）。過去の`y_normalized`運用と比較する場合は`PROGRESS_METHOD=y_normalized`
を明示する。方式名はW&B config、manifest、`result.json`の`progress_method`に記録する。

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

#### Trackのcleanupとイベントarchive

`scripts/02_run_analysis.py`と`scripts/04_multi_video_mae.py`は、毎フレームの更新後に
stale trackをcleanupする。

未確定trackは`CLEANUP_THRESHOLD`を超えて未更新になると削除する。

`COUNTED` trackは履歴全体を保持せず、確定フレームと`s`要約値だけをarchiveへ移す。

`events.csv`はactive trackとarchiveの両方から生成するため、archive移動後も
イベント行数は`count_in + count_out`と一致する。

W&Bには`active_detections`、`retained_states`、`archived_events`を分けて記録する。

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

`roi_setup/setup_roi.py`で保存すると`s_low`/`s_high`（GUIは書き込まない、
`02`/`03`のように手で足す場合のみ）や`roi_setup`メタデータが追加されることがあるが、
`load_configs`は未知キーをそのまま保持するため`04`の処理には影響しない
（詳細は「roi_setup/setup_roi.py — ROI4頂点の手動決定」を参照）。

**出力**: `data/outputs/{EXP_NAME}/mae_{timestamp}/`
```
├── results.csv      # 動画 × パラメータごとの詳細
├── mae_summary.csv  # パラメータごとのMAEサマリー
├── events.csv       # 全run分の確定イベントを集約（先頭に s_low, s_high, video 列）
├── manifests/       # 動画 × パラメータrunごとのmanifest（execution_id.json）
└── diagnostics/     # IN_CANDIDATE停滞trackのJSON/CSV（execution_id単位）
```

`events.csv` の列構成は `02_run_analysis.py` と同じ `track_id, event_type,
frame_index, timestamp_sec, is_warmup` に、どのパラメータ・動画のrunかを示す
`s_low, s_high, video` を先頭に付けたもの。組み合わせ数が多いため個別ファイルに
せず単一の集約CSVにしている。

`events.csv`は`Counter.tracks`とarchiveを結合して生成する。

track IDが再利用された場合も、過去のarchiveイベントと新しいactiveイベントを別行として保存する。

`results.csv`には`tracker_reset`、`tracker_reset_method`、`ultralytics_version`も
記録する。`USE_WANDB=true`の場合は`wandb_run_id`、`execution_id`、`condition_key`と互換用
`exp_key`も記録する。W&Bを無効にした場合も`manifests/`には各runの識別子と
再現情報が残る。

**動画ごとにYOLO推論を1回だけ実行し、閾値ごとのカウントロジックはそのキャッシュを
再生する。**検出結果（バウンディングボックス・track_id）は`s_low`/`s_high`に依存しない
ため、動画1本を`build_detection_trace()`で1回だけ処理し、`(s_low, s_high)`の組み合わせ
ごとには軽量な`replay_counts()`だけを繰り返す。tracker初期化（`prepare_model_for_run`）
も動画ごとに1回。W&B run・manifestの粒度は従来どおり`(s_low, s_high, video)`単位のまま
だが、同じ動画に属する全runのconfigには`detection_cached: true`と、同一キャッシュ由来の
runをグルーピングする`detection_cache_id`が記録される——これらのrunの`read_ms`/
`inference_tracking_ms`は動画単位で共有された実測値であり、統計的に独立ではないことを
示す（`counting_logic_ms`は各runで新規に計測される）。

tracker初期化処理はUltralyticsの内部APIに依存するため、依存バージョンは
`8.4.72`に固定している。バージョン更新時は`test_tracker_lifecycle.py`を含む
ROI counterのテストを実行すること。

`diagnostics/{execution_id}.json`には総track instance数、COUNTED数、
`IN_CANDIDATE`停滞数、停滞trackの`s_max`要約値、`s_high`を0.75/0.70/0.65/0.60へ
下げた場合の机上確定数を保存する。
`diagnostics/{execution_id}.csv`には停滞trackごとのfirst/last seen、s要約値、サンプル数を保存する。

### s_low/s_high 書き戻し履歴（edge_distance）

`data/inputs/configs/IMG_2787_gt.json` の `s_low`/`s_high` は手動編集で更新するため
（`data/` はgit管理外）、更新の根拠はここに追記する。

- 2026-08-20: `s_low=0.20`, `s_high=0.45` に更新（初回のedge_distance検証）。
  根拠: `PROGRESS_METHOD=edge_distance`（既定）で`S_LOW_LIST=0.05..0.45`×
  `S_HIGH_LIST=0.55..0.95`（`EXP_NAME=exp_edge_distance_sweep`）を実行したところ、
  `s_low`は0.05〜0.45の全域で結果に無関係、`s_high`は0.55でMAE=0、0.60で
  早くもMAE=4まで悪化する崖状の分布だった。境界値（0.55）をそのまま採用すると
  頑健性を欠くため、`S_HIGH_LIST=0.20..0.55`まで探索範囲を下方向に拡張して
  再検証（`EXP_NAME=exp_edge_distance_sweep_refine`）したところ、
  `s_high=0.20〜0.55`の全域でMAE=0を確認した。さらに`s_low∈{0.15,0.20,0.25}`×
  `s_high∈{0.40,0.45,0.50}`の2次元グリッドで直接確認（
  `EXP_NAME=exp_edge_distance_sweep_confirm`）し、全9通りでMAE=0であることを
  確認した上で、崖（`s_high=0.60`）から十分な余裕を持つ`s_high=0.45`と、
  確認済みの安全域の中央付近にあたる`s_low=0.20`を採用した。
  **採用値の参照run**（`EXP_NAME=exp_edge_distance_adopted`、採用した
  `s_low=0.20`/`s_high=0.45`のみを再実行して取得した確定run）:

  | 項目 | 値 |
  |---|---|
  | manifest | `data/outputs/exp_edge_distance_adopted/mae_20260820_182314/manifests/990020a9-3b66-4d77-b821-4ca812ba50be.json` |
  | `execution_id` | `990020a9-3b66-4d77-b821-4ca812ba50be` |
  | `wandb_run_id` | `t3u16nn6`（offline: `data/outputs/wandb/offline-run-20260820_183535-t3u16nn6`） |
  | `condition_key` | `ck1_9225ee2ab1d3e34070ae325a8bbcea1805897491106aba8d34fafd865436bcfe` |
  | `git_sha` | `19b58fa229629001bbbf07a48ac23da71b6705be` |
  | 結果 | `IN=22 OUT=0 count_error=0` |

  > **注記1**: 選定の過程で実行した3段階のスイープ
  > （`exp_edge_distance_sweep` / `_refine` / `_confirm`）は、`WANDB_DIR`を指定せずに
  > 実行したためW&Bのrunディレクトリが`data/`の外に生成され、その後のworktree削除で
  > 失われた。上表はそれを受けて採用値のみを`WANDB_DIR=data/outputs`付きで
  > 実行し直した確定runを指す。各スイープの`manifests/`・`mae_summary.csv`自体は
  > `data/outputs/`配下に残っており、選定の再現性は保たれている。
  > 詳細と再発防止策は`VERIFICATION.md`の11章。
  >
  > **注記2**: このrunの`git_dirty`は`true`（`VERIFICATION.md`編集中に実行したため）。
  > カウント結果・閾値・ROIには影響しないが、速度値を厳密に比較する用途には使わないこと。
  >
  > **注記3**: このrunは**W&Bへ同期済み**（2026-08-23）。W&Bプロジェクト
  > `tracking-parking`、group `roi_counter` 内で上記 `condition_key` により検索できる。
  > なお選定過程を含むそれ以前のoffline run（2ライン9件・ROI 6件、08-09〜08-16）は
  > 未同期のまま。いずれも`y_normalized`時代の計測で現在の既定（`edge_distance`）とは
  > 条件が違い、W&B上で直接比較できないため意図的に同期していない。必要になった場合は
  > `data/outputs/wandb/` 配下から個別に`wandb sync`する。

  **既知の限界**: GTが`out=0`の1本のみのため、OUT方向の閾値妥当性は未検証。

---

## analysis/

### 01_visualize_threshold_sweep.py
`03_sweep_params.py` の `results.csv` を読み込んでヒートマップとラインプロットを生成する．

**入力**: `SWEEP_CSV`（`results.csv` のパス）

**出力**: 同ディレクトリに `heatmap_count_error.png`，`line_s_low.png`，`line_s_high.png`，`heatmap_elapsed_ms.png`

---

## 既知の問題

- `main.py`（本番推論）は`counter.cleanup()`を一度も呼んでいない
  （`02_run_analysis.py`・`04_multi_video_mae.py`は毎フレーム呼ぶ）。24/7で
  動かし続けるとstale trackが`Counter.tracks`に無制限に蓄積する可能性がある。
  カウントの意味論に触れる修正のため、ROI設定GUI（層1）の導入時点では
  意図的に直していない。

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
| `CLEANUP_THRESHOLD_SEC` | 未更新trackを削除またはarchiveへ移すまでの秒数（既定5.0） |
| `MAX_CANDIDATE_AGE_SEC` | 候補状態を維持する最大秒数（既定10.0） |
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

未確定trackは`CLEANUP_THRESHOLD_SEC`を超えて未更新になると削除する。

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

- 2026-08-27: `s_low=0.26`, `s_high=0.32` に更新（実カメラ5本を加えた再選定）。
  対象は設定JSON6本すべて。根拠となるデータが1動画から6動画へ増えたため、
  2026-08-20の値（0.20/0.45）を置き換える。

  **データ**: 実カメラで撮影した5本（10fps、各16.7分、合計 IN=96 OUT=7）を追加し、
  従来の`IMG_2787`（30fps、5分、IN=22 OUT=0）と合わせた6本で評価した。
  5本は同一の固定カメラで画角は共通だが、`IMG_2787`とは画角が異なる。
  ROIは`roi_setup/setup_roi.py`で2026-08-26に打ち直した
  （`(577,614) (1343,612) (1615,894) (252,872)`、5本共通）。
  **OUT方向のGTが初めて手に入った**（従来は`out=0`の1本のみだった）。

  **選定過程**: 3回のスイープ（`exp_newdata_sweep` / `exp_slow_frontier` /
  `exp_adopted_confirm`）を同一`git_sha`で実行し、統合した。合計誤差は次のとおり。

  ```
  s_high  0.30  0.32  0.35  0.38  0.40  0.45  0.50  0.55
  s_low
  0.10       5    .      5    .      6    10    14    22
  0.20       5    .      5    .      6    10    14    22
  0.25       3    .      3     4     4     8    12    20
  0.26      .      3     3     4    .     .     .     .
  0.28      .      4     4     3     3     7    .     .
  0.32      .     .     .      4     4     7    .     .
  0.35      .     .     .      6     6     6    .     .
  ```

  **`s_low=0.28`の系列を採らなかった理由**: 誤差3の組み合わせは
  `(0.25,0.30) (0.25,0.35) (0.26,0.32) (0.26,0.35)` と `(0.28,0.38) (0.28,0.40)` の
  2つの塊に分かれ、斜めに並ぶ。後者は補償誤差で成立している。
  `1787009706`のIN内訳を追うと、`s_low`を0.26から0.28へ上げた時点で
  `count_in`が30から31へ増え（GTは30）、`s_high`を0.38へ上げることで実在イベントを
  1件落として30へ戻していた。**偽陽性1件と偽陰性1件が相殺して台数だけが合う状態**で、
  採用する理由がない。`(0.26,0.32)`は相殺なしで30に到達する。

  **余裕の確認**: `events.csv`のs要約列（コミット`9efd31a`で追加）から、
  確定IN 119件の`s_max`は最小0.4006、`s_min`は111件が0.05未満だった。
  `s_high=0.32`は最小到達点まで0.08、平坦域0.30〜0.35の中央にあたる。
  走破幅（`s_max - s_min`）は最小0.359で、閾値差0.06に対して6倍の余裕がある。

  **採用値のrun**（`EXP_NAME=exp_adopted_final`、`data/outputs/exp_adopted_final/mae_20260827_015357`）:

  | 動画 | `execution_id` | `wandb_run_id` |
  |---|---|---|
  | `1787008160.558032.mp4` | `2e76e5a0-0882-482a-9de9-4d7de7ee7c30` | `8e0aam7b` |
  | `1787009706.719727.mp4` | `34bb246a-8a70-4851-b38d-3f2a89b48f99` | `o4ijulrn` |
  | `1787011229.231516.mp4` | `327d1578-6e25-4779-91ef-3377627cb044` | `4awnv564` |
  | `1787012751.179971.mp4` | `0c326dad-d1fb-4b95-99ee-ef78b396db9b` | `zke46ean` |
  | `1787014266.421887.mp4` | `85270e68-ab53-498f-a4a1-0d980c06f621` | `4ylq3mc0` |
  | `IMG_2787.MOV` | `5c5fcd45-c6fa-457c-8b98-da791d3b1e38` | `a8o00pm7` |

  `git_sha=ba615b84be77cdc899783b901e090f02252b5d05`、**`git_dirty=false`**。
  `condition_key`は動画ごとに異なるため各`manifests/{execution_id}.json`を参照する。

  **結果**: 合計誤差3、MAE 0.50。6本中4本が完全一致
  （`1787008160` 55/55、`1787009706` 30/30・OUT 2/2、`1787012751` 7/7・OUT 1/1、
  `IMG_2787` 22/22）。

  **残る誤差2件は閾値では動かない**。どの組み合わせでも合計誤差は3を下回らなかった。

  - `1787011229`: OUT 3件に対しGT 1件。うち`track_id=1`は`n_samples=9420`
    （動画は10001フレーム）で`s`が0.021〜0.999。車両ではなくIDが再利用され続けたtrack
  - `1787014266`: IN 3件に対しGT 2件。`track_id=1460`が`n_samples=344`の同種

  精度の天井を決めているのは閾値ではなくtrackの同一性である。

  **既知の限界**: GTは動画単位の台数のみで、イベント単位の時刻アノテーションは無い。
  したがって台数が合っている動画についても、個々のイベントが正しい車両に対応している
  保証はない。イベント単位の精度（precision / recall / F1）は未計測。

- 2026-08-28 追記: **閾値は変更していない**が、残存誤差3件を映像で検算した結果
  すべてGT側の数え漏れと判明したため、GTを訂正して確定runを取り直した。

  **GTの訂正**（`data/`はgit管理外のため、根拠は各設定JSONの`gt_revision`キーにも記録した）:

  | 設定JSON | 訂正 | 根拠 |
  |---|---|---|
  | `1787011229.231516_gt.json` | `out` 1→3 | 927〜975秒に3台の異なる車両が出庫（緑幌の白軽トラック、平ボディの白軽トラック、黒い軽バン） |
  | `1787014266.421887_gt.json` | `in` 2→3 | `annotated.mp4`のtrack IDで確認。447.5秒の`ID:1535`は赤い乗用車、652.9秒`ID:2106`、846.7秒`ID:2595`の3件とも実在の入庫 |

  **検算の手順**: `02_run_analysis.py`を`SAVE_VIDEO=true`で実行し、track IDを描いた
  `annotated.mp4`で帰属を確定させた。閾値を確定runと揃えたため、出力イベント6件は
  track_id・時刻・s値まで確定runと一致した。**同型車両（白い軽トラック）が複数写る場面では
  静止画では判別できず、ID付き動画が必須だった。**静止画による推測では、別々の2台を
  「1台が駐め直した」と誤読していた。

  **訂正後の確定run**（`EXP_NAME=exp_adopted_final_gtfix`、
  `data/outputs/exp_adopted_final_gtfix/mae_20260828_062140`）:

  | 動画 | `execution_id` | `wandb_run_id` |
  |---|---|---|
  | `1787008160.558032.mp4` | `3f22d943-f9c0-4474-9742-7d1b5be6442c` | `ij9l1mws` |
  | `1787009706.719727.mp4` | `75555cca-5bf3-4ae2-8571-af9ade46197f` | `h7nwtnea` |
  | `1787011229.231516.mp4` | `ac0d4711-d2cc-4d0e-82d1-25e783a6b5a9` | `votntf1x` |
  | `1787012751.179971.mp4` | `526413f8-a11b-4bc4-b75c-2c62bd5a8fc7` | `ht48lybd` |
  | `1787014266.421887.mp4` | `d7be0e77-74e8-494f-8b04-85bf0115a6a8` | `spdikx1c` |
  | `IMG_2787.MOV` | `1b9f6f4c-caba-49d4-a962-db0ef5fa69c2` | `39gkxacj` |

  `git_sha=2992885c`、`git_dirty=false`。
  **結果: 合計誤差0、MAE 0.00、6本すべて完全一致。検出側の誤りは1件も残っていない。**

  GT訂正により`ground_truth_sha256`が変わるため、`condition_key`は訂正前のrunと異なる。
  条件変更に伴う想定内の挙動である。訂正前の選定用run（`exp_adopted_final` /
  `mae_20260827_015357`）は、訂正前GTに対する記録としてW&Bに残している。

  **`n_samples`は異常の指標にならない**（検算で判明）。`Counter.update()`は状態に関係なく
  加算し、`COUNTED`のtrackも`cleanup()`がarchiveへ移すまで更新され続けるため、ROI内の
  駐車枠に駐まった車はカウント確定後も伸び続ける。有効な異常指標は`s_max`が小さいこと
  （浅い到達）と`s_min`が大きいこと（浅い進入）である。

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

## 時間窓は秒で持つ

`CLEANUP_THRESHOLD_SEC`と`MAX_CANDIDATE_AGE_SEC`は秒で指定し、動画を開いた時点の
fpsからフレーム数へ変換する（`common/time_windows.py`の`frames_from_seconds`）。

フレーム数で直接持つと、同じ設定値が撮影fpsによって別の長さを意味してしまう。
150フレームは30fpsで5秒だが、10fpsでは15秒になる。**検証に使ってきた動画は30fps、
実機のRaspberry Piは10fps前後で動く**ため、フレーム基準のままでは検証と実運用の
あいだに黙って差が入る。

既定値（5.0秒・10.0秒）は、旧既定のフレーム数（150・300）を30fpsで換算した値と
一致する。30fpsの動画では挙動が変わらない。

runには秒と変換後のフレーム数の両方を記録する。

| キー | 内容 |
|---|---|
| `cleanup_threshold_sec` / `max_candidate_age_sec` | 設定した秒数（仕様） |
| `cleanup_threshold` / `max_candidate_age` | 変換後のフレーム数（実際の挙動） |

`condition_key`に入るのは変換後のフレーム数である。秒数が同じでもfpsが違えば
別条件になる、という扱いになる。

fpsを取得できない動画は`build_detection_trace`が`None`を返して計測対象から外す。
窓の長さが不定のまま計測しないため。

2ライン方式の`MAX_FRAME_GAP_SEC`も同じ仕組みで、`frames_from_seconds`を共有する。

## W&Bの運用方針

2026-08-26に次の4点を決定した。根拠となる実測は`VERIFICATION.md`の0章にある。

**一次記録はローカル成果物、W&Bは二次的な閲覧先**。
`manifests/{execution_id}.json`は`USE_WANDB`の値に関係なく書かれ、
`results.csv`、`mae_summary.csv`、`events.csv`、`frames.csv`も同様に残る。
方式の比較と再現に必要な数値はW&Bを無効にしても失われない。
この前提を崩す変更（W&Bにしか残らない値を増やす）は入れない。

**`WANDB_MODE`は`offline`固定**。
`online`はネットワークへ到達できない環境で`wandb.init()`がハングし、
`init_timeout`でも打ち切れないため採用しない。
アップロードは`wandb sync`で後から行う。

**本番推論（`main.py`）はW&Bへ記録しない**。
ネットワーク断が入出庫カウントの停止に直結するため、24/7で動く監視系に
その依存を持ち込まない。実装漏れではなく決定である。

**検証手順で回すrunはW&Bへ残す**。
`04_multi_video_mae.py`（閾値スイープ）と`02_run_analysis.py`（詳細分析）は
`USE_WANDB=true WANDB_MODE=offline WANDB_DIR=data/outputs`付きで実行する。
2ライン方式の`main.py`も同様（`raspi/line_detection/VERIFICATION.md`）。

スクリプトごとの対応状況は次のとおり。

| スクリプト | W&B | 記録の粒度 |
|---|---|---|
| `scripts/04_multi_video_mae.py` | 対応 | config + summary（時系列なし） |
| `scripts/02_run_analysis.py` | 対応 | config + 時系列 + summary |
| `main.py` | 非対応（決定） | 標準出力のみ |
| `scripts/03_sweep_params.py` | 非対応 | `04`に置き換わった旧スイープ |
| `scripts/01_show_roi.py`、`roi_setup/setup_roi.py` | 非対応 | 計測ではなく設定と確認のツール |

将来`online`へ切り替える場合、および`main.py`をW&Bへ繋ぐ場合は、
`wandb.init()`の失敗時に`enabled=False`へ降格して計測本体を続行する改修が前提になる。
`ExperimentLogger`は`enabled=False`で完全なno-opになるため、降格の受け皿は既にある。

## 既知の問題

- `main.py`（本番推論）は`counter.cleanup()`を一度も呼んでいない
  （`02_run_analysis.py`・`04_multi_video_mae.py`は毎フレーム呼ぶ）。24/7で
  動かし続けるとstale trackが`Counter.tracks`に無制限に蓄積する可能性がある。
  カウントの意味論に触れる修正のため、ROI設定GUI（層1）の導入時点では
  意図的に直していない。

# roi-counter

ROI内を通過する車両の進行度 `s` を用いて入庫・出庫を判定するカウントシステム．

## ディレクトリ構造

```
roi-counter/
├── src/                    # コアモジュール
│   ├── roi.py              # ROI判定・y範囲取得
│   ├── progress.py         # 進行度 s の計算
│   ├── tracker.py          # 車両状態データクラス
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
└── annotated.mp4   # 可視化済み動画
```

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
s_low, s_high, count_in, count_out, gt_in, gt_out, count_error, elapsed_ms, mean_frame_ms, max_frame_ms
```

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
└── mae_summary.csv  # パラメータごとのMAEサマリー
```

---

## analysis/

### 01_visualize_threshold_sweep.py
`03_sweep_params.py` の `results.csv` を読み込んでヒートマップとラインプロットを生成する．

**入力**: `SWEEP_CSV`（`results.csv` のパス）

**出力**: 同ディレクトリに `heatmap_count_error.png`，`line_s_low.png`，`line_s_high.png`，`heatmap_elapsed_ms.png`

# 2ライン検知システム

駐車場の出入り検知精度を向上させる2ライン検知システムです。Line1(入口側)とLine2(駐車場側)の2本のラインを使用し、車両の通過順序と方向から高精度な入出庫カウントを実現します。

## 特徴

- **ハイブリッド方式**: Line1が主判定、Line2が信頼度を付与
- **外積法による高精度判定**: 数学的に正確なライン交差検知
- **GUIライン設定ツール**: 動画を見ながら対話的にライン座標を設定
- **YOLOv8トラッキング**: 最新の物体検知・追跡技術
- **詳細なログ出力**: JSON/CSV形式で解析しやすい
- **リアルタイム可視化**: アノテーション付き動画の生成

## ディレクトリ構造

```
raspi/line_detection/
├── .env                           # 環境設定
├── .env.template                  # 設定テンプレート
├── requirements.txt               # 依存パッケージ
├── README.md                      # このファイル
├── main.py                        # メイン処理
│
├── line_setup/                    # ライン座標設定ツール
│   └── setup_lines.py            # GUIでライン位置を設定
│
├── detection/                     # 車両検知・ライン交差判定
│   ├── config.py                 # 設定管理
│   ├── line_crossing.py          # ライン交差検知(外積法)
│   └── tracker.py                # 車両トラッキング・状態管理
│
├── result_output/                 # 結果出力
│   ├── video_writer.py           # アノテーション動画生成
│   └── event_logger.py           # イベントログ出力
│
└── data/                          # データ
    ├── inputs/                   # 入力動画(.mp4)
    └── outputs/                  # 出力結果
        ├── videos/               # アノテーション済み動画
        └── logs/                 # イベントログ(JSON/CSV)
```

## セットアップ

### 1. 依存パッケージのインストール

プロジェクトルートディレクトリ(`tracking-parking/`)でuvを使ってインストールします:

```bash
cd /path/to/tracking-parking
uv sync
```

これにより、`pyproject.toml`に定義された2ライン検知システムに必要な依存パッケージがすべてインストールされます。

**インストールされるパッケージ:**
- ultralytics (YOLOv8)
- opencv-python (動画処理)
- python-dotenv (設定管理)
- numpy (数値演算)
- torch, torchvision (深層学習)
- pandas (データ処理)
- wandb (実験管理・offline記録)

### 2. ライン座標の設定

GUIツールを使って2本のラインと駐車場基準点を設定します:

```bash
python line_setup/setup_lines.py --video data/inputs/test.mp4
```

**操作方法:**
1. 動画の最初のフレームが表示されます
2. 以下の順番で5点をクリックしてください:
   - **Line1 始点** (入口側ライン)
   - **Line1 終点** (入口側ライン)
   - **Line2 始点** (駐車場側ライン)
   - **Line2 終点** (駐車場側ライン)
   - **駐車場基準点** (駐車場内の任意の点)
3. 設定が`.env`ファイルに自動保存されます

**キー操作:**
- `r`: やり直し
- `q`: 終了

### 3. 動画の配置

処理したい動画を`data/inputs/`に配置します:

```bash
cp /path/to/your/video.mp4 data/inputs/
```

## 使用方法

### 基本的な使用方法

```bash
python main.py --input data/inputs/test.mp4
```

### リアルタイム表示

処理中の動画を表示しながら実行:

```bash
python main.py --input data/inputs/test.mp4 --display
```

### カメラからリアルタイム処理

```bash
python main.py --camera 0 --display
```

### 出力先を指定

```bash
python main.py --input data/inputs/test.mp4 --output /path/to/output
```

### 方式間の速度比較

速度計測は timing schema v2 に従い、`read_ms`、`inference_tracking_ms`、
`counting_logic_ms`、`core_ms`、`output_ms`、`end_to_end_ms` に分割する。
方式比較では warm-up 除外後の `core_ms_p95`、実機のリアルタイム判定では
`end_to_end_ms` と `deadline_miss_rate` を使用する。

ROI方式と同じ動画・モデル・classes・confidence・IoU・image size・tracker・device・
warm-up・動画保存/表示設定を指定して実行する。
ROI方式の現在の既定値は`VEHICLE_CLASSES=2,7`、`CONFIDENCE_THRESHOLD=0.25`、
`IOU_THRESHOLD=0.7`であり、`.env.template`もこの比較条件に揃えている。

```bash
WARMUP_FRAMES=30 YOLO_DEVICE=cpu YOLO_IMGSZ=640 \
YOLO_TRACKER=botsort.yaml SAVE_VIDEO=false SHOW_DISPLAY=false \
WANDB_MODE=offline python main.py --input data/inputs/test.mp4 \
  --wandb --device-name raspi5
```

入力・モデルのSHA-256と上記条件から生成した`comparison_key`が同じrunだけを
直接比較する。W&B送信は計測区間外で行うため、online/offlineの通信状態は
速度値に含まれない。offline runは後日次のように同期する。

実験runの識別には、用途を分けた次の値を使用する。

- `condition_key`: Line1・Line2・駐車場基準点、検知パラメータ、入力・モデルhash、
  Git・主要ライブラリ版などの型付きcanonical JSONから生成する条件hash
- `execution_id`: 同条件の再実行も区別する実行ごとのUUID
- `wandb_run_id`: W&Bが発行するID（W&B有効時のみ）
- `display_name`: W&B UI向けの可読名。一意性の判定には使用しない

旧`exp_key`は移行期間中のみ`condition_key`のaliasとして残す。

```bash
wandb sync <run_dir>
```

### 台数精度の比較（GT）

正解台数(GT)のJSONを`--gt`で指定すると、検出結果との差を`count_error`として
記録する。ROI方式と同じGTファイルを共有し、`roi`キー等ROI方式固有の項目は
無視する。

```bash
python main.py --input data/inputs/test.mp4 \
  --gt ../roi-counter/data/inputs/configs/IMG_2787_gt.json
```

`--gt`を省略した場合は`<動画名>_gt.json`を入力動画と同じディレクトリから
自動探索する。見つからなければ警告のみでGT比較なしのまま続行する。
`--gt`で明示的に指定したパスが存在しない場合は起動時にエラーで停止する。

GTのJSON形式:

```json
{
  "in": 22,
  "out": 0
}
```

- 値が数値(`0`を含む)なら「確認済み」として評価する
- 値が`null`または省略時は「未確認」として**その方向は評価対象から除外**する
  (`0`と`null`は明確に区別する)

記録されるキー:

- `gt_in` / `gt_out`: GTの値(未確認は`None`)
- `count_error_in` / `count_error_out`: 方向ごとの絶対誤差(未評価の方向は`None`)
- `count_error`: 評価した方向の誤差合計。**評価方向数によってスケールが変わるため、
  ROI方式の`04_multi_video_mae.py`と直接比較してよいのはIN/OUT両方が評価済みのときだけ**。
  片方のみの評価では方向別キー(`count_error_in`等)を使うこと

GT情報(`ground_truth_sha256`・`gt_in`・`gt_out`)は`condition_key`に含まれるため、
GTの有無・内容が変わると同一条件とはみなされなくなる。

> **注意**: ROI方式の`04_multi_video_mae.py`はGTの`out`が`null`だとエラーになる。
> `null`を含むGTをROI方式の`GT_DIR`に置かないこと。

## 出力ファイル

W&Bの有効・無効にかかわらず、runごとに
`data/outputs/manifests/{execution_id}.json`を保存する。manifestには上記ID、
完全な実験config、イベントログ・CSV・動画の絶対パスを記録する。

### アノテーション動画 (`data/outputs/videos/`)

元の動画に以下の情報を重ねて表示:
- Line1 (緑色) - 入口側ライン
- Line2 (黄色) - 駐車場側ライン
- 車両代表点とtrack_ID
- リアルタイムカウント(入庫/出庫/駐車台数)
- 処理時間

### イベントログ JSON (`data/outputs/logs/events_YYYYMMDD_HHMMSS.json`)

```json
{
  "video_path": "data/inputs/test.mp4",
  "processed_at": "2026-06-24T10:30:00",
  "execution_id": "d45174ea-4de7-4bac-9d44-1ab9c86bd07a",
  "condition_key": "ck1_...",
  "total_frames": 900,
  "avg_processing_time_ms": 48.5,
  "events": [
    {
      "track_id": 1,
      "event_type": "IN",
      "frame_id": 145,
      "timestamp_sec": 4.83,
      "confidence": "high",
      "line2_crossed": true
    }
  ],
  "summary": {
    "total_in": 5,
    "total_out": 3,
    "current_parked": 2,
    "high_confidence_events": 6,
    "normal_confidence_events": 2
  },
  "accuracy": {
    "gt_in": 22,
    "gt_out": 0,
    "count_error": 3,
    "count_error_in": 2,
    "count_error_out": 1
  }
}
```

`accuracy`ブロックは`--gt`でGTを指定した場合のみ追加される。GTを指定しない
実行では従来どおりこのキー自体が存在しない。

### イベントログ CSV (`data/outputs/logs/events_YYYYMMDD_HHMMSS.csv`)

Excelで開きやすいCSV形式:

```csv
track_id,event_type,frame_id,timestamp_sec,confidence,line2_crossed
1,IN,145,4.83,high,true
2,OUT,203,6.77,normal,false
```

## 設定パラメータ

`.env`ファイルで以下のパラメータを調整できます:

### YOLOモデル設定

```bash
MODEL_PATH=/path/to/yolov8s.pt
CONFIDENCE_THRESHOLD=0.3  # 検知信頼度閾値(0.0-1.0)
```

### ライン座標

`setup_lines.py`で自動設定されます。

### 検知パラメータ

```bash
MARGIN_PX=0.0              # 判定保留帯の半幅(px)。3cで正式決定
ENDPOINT_MARGIN_PX=0.0     # 有限線分判定の端点許容量(px)
MAX_FRAME_GAP=90          # Line1とLine2の最大フレーム差(3秒@30fps)
CLEANUP_THRESHOLD=150      # 古い追跡をクリーンアップ(5秒@30fps)
```

### 出力設定

```bash
SAVE_VIDEO=true           # アノテーション動画を保存
SAVE_LOGS=true            # ログを保存
SHOW_DISPLAY=false        # リアルタイム表示
```

## アルゴリズム

### 外積法によるライン交差検知

2D平面上のベクトル外積を使用してライン交差を判定:

```
外積 = (line_end - line_start) × (point - line_start)
```

- 外積 > 0: ポイントはラインの片側
- 外積 < 0: ポイントはラインの反対側
- 外積の符号が変化 = ライン交差

### ハイブリッド方式の判定ロジック

```
IF Line1を交差:
    IF 方向 == IN:
        IF Line2もLine1の後に交差(max_frame_gap以内):
            -> 入庫(信頼度: HIGH)
        ELSE:
            -> 入庫(信頼度: NORMAL)

    IF 方向 == OUT:
        IF Line2がLine1の前に交差(max_frame_gap以内):
            -> 出庫(信頼度: HIGH)
        ELSE:
            -> 出庫(信頼度: NORMAL)

IF Line2のみ交差(Line1交差なし):
    -> カウントしない(駐車スペース内の移動)
```

## トラブルシューティング

### `.env`ファイルが見つからない

```
エラー: .envファイルが見つかりません
```

**解決方法:** まず`setup_lines.py`を実行してライン座標を設定してください。

### YOLOモデルが見つからない

```
設定エラー: モデルファイルが見つかりません
```

**解決方法:** `.env`の`MODEL_PATH`を正しいパスに修正してください。

### カウントが不正確

**考えられる原因:**
1. ライン位置が適切でない → `setup_lines.py`で再設定
2. `MARGIN_PX`が大きすぎる/小さすぎる → `.env`で調整(px単位)
3. `MAX_FRAME_GAP`が適切でない → 車両の通過速度に合わせて調整

## 参考

- [GitHub Issue #88](https://github.com/NUTFes/tracking-parking/issues/88) - 設計仕様
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) - 物体検知モデル

## ライセンス

このプロジェクトのライセンスについては、リポジトリのルートディレクトリを参照してください。

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

## 出力ファイル

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
  }
}
```

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
MARGIN=1000.0              # ライン交差判定のマージン
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
2. `MARGIN`が大きすぎる/小さすぎる → `.env`で調整
3. `MAX_FRAME_GAP`が適切でない → 車両の通過速度に合わせて調整

## 参考

- [GitHub Issue #88](https://github.com/NUTFes/tracking-parking/issues/88) - 設計仕様
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) - 物体検知モデル

## ライセンス

このプロジェクトのライセンスについては、リポジトリのルートディレクトリを参照してください。

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
tracking-parking/
├── .env                           # 環境設定(ローカル)
├── .env.template                  # 設定テンプレート
├── pyproject.toml                 # 依存パッケージ定義(uv)
│
├── scripts/                       # CLIエントリポイント
│   ├── run_detection.py          # メイン処理
│   ├── setup_lines.py            # GUIでライン位置を設定
│   ├── visualize_lines.py        # ライン・車両代表点の可視化
│   └── run_multi_video.py        # 複数動画の一括処理と集約
│
├── src/tracking_parking/          # 本体パッケージ
│   ├── config.py                 # 設定管理
│   ├── detection/                # 車両検知・ライン交差判定
│   │   ├── line_crossing.py     # ライン交差検知(外積法)
│   │   └── tracker.py           # 車両トラッキング・状態管理
│   ├── output/                   # 結果出力
│   │   ├── video_writer.py      # アノテーション描画
│   │   ├── video_recorder.py    # 録画先(NVENC/CPU、サイズ分割)
│   │   └── event_logger.py      # イベントログ出力
│   ├── common/                   # 計測・GT・W&Bの共通基盤
│   └── eval/                     # 精度評価
│
├── tests/                         # テスト
├── models/                        # YOLOモデル重み(.pt、Git管理外)
└── data/                          # データ(Git管理外)
    ├── inputs/                   # 入力動画(.mp4)
    │   ├── configs/              # 正解台数GT(<動画名>_gt.json)
    │   ├── videos.example.json   # 複数動画処理の対象リスト雛形(Git管理下)
    │   └── videos.json           # 同・実体
    └── outputs/                  # 出力結果
        ├── videos/               # アノテーション済み動画
        │   └── camera_<開始時刻>/  # カメラ入力は分割して書く
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

**エッジ機(Jetson Orin NX)では`uv sync`と`uv run`を使ってはいけない。** どちらも
`.venv`をuv管理のPythonで作り直し、torchをPyPIの汎用ビルドへ置き換えるため、
JetPackのCUDAドライバでは初期化できなくなる。手順はREADMEの「エッジ機」を参照。

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
python scripts/setup_lines.py --video data/inputs/test.mp4
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
python scripts/run_detection.py --input data/inputs/test.mp4
```

### リアルタイム表示

処理中の動画を表示しながら実行:

```bash
python scripts/run_detection.py --input data/inputs/test.mp4 --display
```

### カメラからリアルタイム処理

```bash
python scripts/run_detection.py --camera 0 --display
```

### 出力先を指定

```bash
python scripts/run_detection.py --input data/inputs/test.mp4 --output /path/to/output
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
WANDB_MODE=offline python scripts/run_detection.py --input data/inputs/test.mp4 \
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
記録する。GTファイルは`in`/`out`以外のキーを持っていても無視される。

```bash
python scripts/run_detection.py --input data/inputs/test.mp4 \
  --gt data/inputs/configs/IMG_2787_gt.json
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
- `count_error`: 評価した方向の誤差合計。**評価方向数によってスケールが変わる**ため、
  run間で比較してよいのは評価方向が揃っているときだけ。
  片方のみの評価では方向別キー(`count_error_in`等)を使うこと

GT情報(`ground_truth_sha256`・`gt_in`・`gt_out`)は`condition_key`に含まれるため、
GTの有無・内容が変わると同一条件とはみなされなくなる。


## 出力ファイル

W&Bの有効・無効にかかわらず、runごとに
`data/outputs/manifests/{execution_id}.json`を保存する。manifestには上記ID、
完全な実験config、イベントログ・CSV・動画の絶対パスを記録する。

### アノテーション動画 (`data/outputs/videos/`)

元の動画に以下の情報を重ねて表示:
- **日本時刻**（`2026-09-18 11:29:04 JST`）- APIへ送る`detected_at`と同じ値
- Line1 (緑色) - 入口側ライン
- Line2 (黄色) - 駐車場側ライン
- 車両代表点とtrack_ID
- リアルタイムカウント(入庫/出庫/駐車台数)
- 処理時間

焼き込む文字列はすべてASCII。`cv2.putText`が使うHersheyフォントはASCIIしか持たず、
非ASCIIは1文字ずつ`?`として描かれる（`"Line1 (入口側)"`は`"Line1 (???)"`になる）。
この環境のOpenCVは`freetype`モジュールを含まないためTTF描画へ逃げられない。
日本語の説明は動画ではなく端末側に出す。

時刻を焼き込むのは、事後分析で動画のどの位置がいつなのかを知る必要があるため。
`frame_read_at`（APIの`detected_at`と同じ値）を使うので、イベント記録と突き合わせ
られる。タイムゾーンは固定オフセット+09:00へ変換する。機体の設定がUTCのままでも
日本時刻を焼き込むためで、JSTは夏時間が無いので固定で厳密に表せる。

出力のレイアウトは入力の種類で変わる。

```
data/outputs/videos/
  camera_20260918_143000/        # カメラ入力: 実行開始時刻のディレクトリへ分割
      segment_00000.mp4
      segment_00001.mp4
  annotated_<入力名>.mp4          # 動画ファイル入力: 単一ファイル
```

カメラ入力を分割するのは、mp4のインデックス(moov atom)が終了時に書かれるため、
分割しないままプロセスが落ちると**それまでの全録画が再生不能になる**ため
（`SIGKILL`で落とすと`ffprobe`が`moov atom not found`を返すことを実測で確認した）。
分割しておけば失うのは書きかけの1本だけで済む。

分割の基準は時間ではなくサイズ（`VIDEO_SEGMENT_MB`）。`splitmuxsink`の
`max-size-time`はバッファのタイムスタンプ基準で、これは公称fpsから作られるため、
実効fpsと一致しない環境では「10分」の指定が実時間で約25分になる。バイト数は
このずれを受けない。各セグメントの正確な時刻は焼き込んだJSTから読む。

`VIDEO_MAX_SEGMENTS`を1以上にすると**ファイル名が循環する**。`splitmuxsink`の
`max-files`がリングバッファとして動くためで、2400フレームを`max-files=3`で流すと
index 0..2の3本だけが残り、mtimeでは`segment_00000`が最新だった。
**名前から時系列は読めない**ので、mtimeか焼き込んだJSTで判断する。既定は0（無制限）で、
事後分析用の証跡を黙って消さない。

エンコーダは`VIDEO_ENCODER`で選ぶ（`auto`/`nvenc`/`cv2`）。`auto`はNVENCが使えれば
使い、無ければCPUへ落ちる。1280x720での書き込みはNVENCが約5.3ms/フレーム、
CPU(mp4v)が約11.6msで、検知ループのフレーム予算に直接効く。詳細は
[decisions/0003-camera-input-and-recording.md](decisions/0003-camera-input-and-recording.md)。

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
MARGIN_PX=5.0              # 判定保留帯の半幅(px)。3cスイープ採用値
ENDPOINT_MARGIN_PX=0.0     # 有限線分判定の端点許容量(px)
MAX_FRAME_GAP_SEC=3.0      # Line1とLine2の通過を対応付ける最大の時間差(秒)
CLEANUP_THRESHOLD_SEC=5.0  # 古い追跡をクリーンアップするまでの未更新時間(秒)
```

**時間窓は秒で指定し、判定も秒で行う。** フレーム数で直接持つと、同じ設定値が
撮影fpsによって別の長さを意味してしまう。90フレームは30fpsで3秒だが、10fpsでは9秒に
なる。検証に使ってきた動画は30fps、実機のRaspberry Piは10fps前後で動くため、
フレーム基準のままでは検証と実運用のあいだに黙って差が入る。

判定に使うのは「ストリーム時刻」で、入力の種類で作り方が変わる
（`scripts/run_detection.py`の`compute_stream_time_sec`）。

| 入力 | ストリーム時刻 | 理由 |
|---|---|---|
| 動画ファイル | `frame_id / fps` | 全フレームを順に処理するので、処理が何秒かかっても映像内の経過は変わらない。再現性が保たれる |
| カメラ | 処理開始からの実経過 | 処理が撮影レートに追いつかないとドライバのバッファ(4枚)で古いフレームが捨てられ、処理したフレーム数は実経過より少なくなる |

**カメラで実経過を使うのは、公称fpsが実効fpsと一致しないため。** Jetson Orin NXで
Logitech C270を使うと、公称30fpsに対し実測は約14fps（推論60ms＋MJPGデコード11ms）
だった。`frame_id / fps` で換算すると「3秒」の窓が実時間で6秒以上に伸び、Line1と
Line2の対応付けとtrackのクリーンアップの両方がずれる。これは動画ファイルでは
再現せず、ライブカメラを繋いだときだけ現れる。

既定値（3.0秒・5.0秒）は旧既定のフレーム数（90・150）を30fpsで換算した値と一致する。
30fpsの動画では挙動が変わらない（検証クリップのイベントログが変更前後で完全一致する
ことを確認済み）。runには秒（`max_frame_gap_sec`）と、参考値として動画入力での換算後の
フレーム数（`max_frame_gap_frames`、カメラでは`null`）を記録する。
**`condition_key`に入るのは秒のほう**で、トラッカーの実際の判定単位がそちらだから。

旧`MAX_FRAME_GAP`／`CLEANUP_THRESHOLD`が`.env`に残っている場合は、黙って無視せず
起動時にエラーで移行を促す。

### 出力設定

```bash
SAVE_VIDEO=true           # アノテーション動画を保存
SAVE_LOGS=true            # ログを保存
SHOW_DISPLAY=false        # リアルタイム表示
```

### API送信設定

```bash
API_ENABLED=false                                    # カメラ入力かつtrueのときだけ送信する
API_BASE_URL=                                        # 例: http://localhost:8000/api/v1
DEVICE_API_KEY=                                       # デバイス登録時に一度だけ返る平文キー
API_CONNECT_TIMEOUT_SEC=3.0                          # 接続確立の待ち時間
API_READ_TIMEOUT_SEC=5.0                             # 応答の待ち時間
HEARTBEAT_INTERVAL_SEC=30                            # サーバーのオフライン判定(既定120秒)の4分の1
SHUTDOWN_FLUSH_SEC=10                                # 終了時にキューが空になるのを待つ上限(秒)
SPOOL_PATH=data/outputs/unsent_events.jsonl          # 送れなかったイベントの置き場所(相対パスはHOME_DIR基準)
```

カメラ入力かつ `API_ENABLED=true` のときだけ、入出庫イベントと集計開始/停止コマンドの
往復（ハートビート）を行う。動画ファイル入力では常に送信しない。`--no-api` を付けると
`.env` を書き換えずに送信だけを無効化できる（実機デバッグ用。逆向きの「ファイル入力でも
強制送信する」オプションは安全性の理由から提供しない）。

送信するイベントには `request_id`（ローカルの `event_id`、UUID）を必ず含める。サーバー側は
同じ `request_id` の2回目を既存イベントとして扱い `system_count` を動かさないため、
接続タイムアウトや応答不明などの失敗はすべて安全に再送できる。`POST /events` は
イベントの永続化と同時に **202 Accepted** を返し、`system_count` への反映は
サーバー側のバックグラウンド処理に回る（同期的には反映されない）。設計の詳細は
[docs/decisions/0002-api-event-delivery.md](decisions/0002-api-event-delivery.md) を参照。

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
        IF Line2もLine1の後に交差(max_frame_gap_sec以内):
            -> 入庫(信頼度: HIGH)
        ELSE:
            -> 入庫(信頼度: NORMAL)

    IF 方向 == OUT:
        IF Line2がLine1の前に交差(max_frame_gap_sec以内):
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
3. `MAX_FRAME_GAP_SEC`が適切でない → 車両の通過速度に合わせて調整

## 参考

- [GitHub Issue #88](https://github.com/NUTFes/tracking-parking/issues/88) - 設計仕様
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) - 物体検知モデル

## ライセンス

このプロジェクトのライセンスについては、リポジトリのルートディレクトリを参照してください。

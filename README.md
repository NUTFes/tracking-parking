# tracking-parking

駐車場の入出庫を検知し、駐車台数を管理するシステム。

車両の検知には**2ライン方式**を採用している。出入口側の `Line1` を主判定ライン、
奥側の `Line2` を補助判定ラインとして、YOLOv8のトラッキング結果からライン通過を
検知し、入庫・出庫をカウントする。方式選定の経緯は
[docs/decisions/0001-two-line-method.md](docs/decisions/0001-two-line-method.md) を参照。

プロジェクト全体の背景は [Wiki](https://github.com/NUTFes/tracking-parking/wiki) にある。

## セットアップ

### 開発機（macOS / Linux、GPUを使わない）

```bash
uv sync
```

`src/tracking_parking` がeditable installされ、`import tracking_parking` が使えるようになる。

### エッジ機（Jetson Orin NX / JetPack 6.x）

**`uv sync` と `uv run` を使ってはいけない。** どちらも暗黙に `.venv` を uv 管理の
Pythonで作り直し、torchをPyPIの汎用ビルドへ置き換える。JetPackのCUDAドライバ(12.6)
では初期化できず、`torch.cuda.is_available()` が `False` になって
`ValueError: Invalid CUDA 'device=0' requested` で止まる。

GPU実行に必要な torch / torchvision / OpenCV / ultralytics は**システムPython 3.10側**に
入っているため、`.venv` はそれを借りる形で作る。

```bash
uv venv --python 3.10 --system-site-packages
uv pip install --python .venv/bin/python "python-dotenv>=1.0.0" "pandas>=2.2.1" \
  "scipy>=1.13" "requests>=2.32.0" "urllib3>=2.0.0" tqdm pytest wandb
uv pip install --python .venv/bin/python --no-deps -e .
```

以降はすべて `.venv/bin/python` を直接呼ぶ。

```bash
.venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# → 2.11.0 True   （Falseなら上の手順をやり直す）
```

### 共通

設定ファイルとモデル重み、入力動画を用意する。いずれもGit管理外。

```bash
cp .env.template .env          # HOME_DIR と MODEL_PATH を環境に合わせる
mkdir -p models data/inputs    # models/ に .pt を、data/inputs/ に動画を置く
```

## 使い方

エッジ機では `uv run python` を `.venv/bin/python` に読み替える（理由は上のセットアップ参照）。

```bash
# 1. GUIでライン座標を設定する（先頭フレームに5点クリック）
uv run python scripts/setup_lines.py --video data/inputs/test.mp4
uv run python scripts/setup_lines.py --camera 0     # 設置カメラの画角で直接設定する

# 2. 動画を処理して入出庫をカウントする
uv run python scripts/run_detection.py --input data/inputs/test.mp4

# 3. ライン位置と車両代表点の関係を確認する
uv run python scripts/visualize_lines.py data/inputs/test.mp4

# 4. 複数動画をまとめて処理し、サマリーへ集約する
#    対象動画は data/inputs/videos.json に書く（雛形は videos.example.json）
cp data/inputs/videos.example.json data/inputs/videos.json
uv run python scripts/run_multi_video.py
```

結果は `data/outputs/` に出る（アノテーション動画、イベントログのJSON/CSV、run manifest）。

**ライン座標は設定したときの画角に紐づく。** カメラ入力では実行時の解像度が
それと違うと検知位置がずれるため、`.env` の `CAMERA_WIDTH` / `CAMERA_HEIGHT` /
`CAMERA_FOURCC` を明示すること（未設定だとデバイス既定で開く）。`setup_lines.py`
も同じ設定でフレームを掴むので、両者は自動的に揃う。

## 録画（事後分析用）

`SAVE_VIDEO=true` でアノテーション動画を保存する。ライン・車両代表点・track_ID・
カウント数に加えて、各フレームへ**日本時刻**を焼き込む（イベント記録の
`detected_at` と同じ値なので、動画の位置とイベントを突き合わせられる）。

```
data/outputs/videos/
  camera_20260918_143000/        # カメラ入力: 実行開始時刻のディレクトリへ分割して書く
      segment_00000.mp4
      segment_00001.mp4
  annotated_<入力名>.mp4          # 動画ファイル入力: 単一ファイル
```

カメラ入力を分割するのは、mp4のインデックス(moov atom)が終了時に書かれるため、
分割しないままプロセスが落ちると**それまでの全録画が再生不能になる**ため。
分割しておけば失うのは書きかけの1本だけで済む。閾値は `VIDEO_SEGMENT_MB`。

JetsonではNVENC（ハードウェアエンコーダ）を使う。1280x720で書き込みが
約5.3ms/フレームで、CPU(mp4v)の約11.6msより検知ループのフレーム予算を食わない。
`VIDEO_ENCODER=auto` なら使える環境で自動的に選ばれる。

設定キーと測定値の詳細、この設計に至った経緯は
[docs/decisions/0003-camera-input-and-recording.md](docs/decisions/0003-camera-input-and-recording.md) を参照。

## 本番実行（エッジ機）

ライン設定だけGUIでの手作業が要るため、初回の設定と繰り返す実行を分けている。

```bash
# 初回のみ（画角を変えたときも）: 設置カメラの画角でライン座標を設定する
scripts/setup_production_lines.sh

# 毎回: 事前チェック → 検知 → API送信 → 録画
scripts/run_production.sh
```

`run_production.sh` は `jetson-production.env`（API設定）を環境へ入れてから
`jetson-newcam.env`（検知設定）で起動する。`run_detection.py --env` は指定ファイル
だけを読むため、API設定は環境変数で渡す必要がある。差し替えは環境変数で行う
（`DETECT_ENV` / `API_ENV` / `CAMERA` / `PYTHON` / `LOG_DIR`）。

**事前チェックで止まる条件**（`scripts/preflight.py` 単体でも実行できる）:

- CUDAが使えない（`uv sync` / `uv run` で `.venv` が作り直された場合）
- カメラを開けない、または要求解像度が受理されなかった
- **ライン座標が画角の外にある** — 起動はするが一度も交差せず、イベントが
  ゼロのまま静かに動き続けるため、実行前に捕まえる
- `API_ENABLED=true` なのに `DEVICE_API_KEY` が空
- 録画先の空き容量が少ない

停止は `Ctrl+C`（SIGINT）。`finally` を通って
`cap.release()` → `out.release()` → `api.shutdown()` の順で後片付けし、
録画の最後のセグメントも再生可能な状態で確定する。`kill -9` では書きかけの
1本が再生不能になる（分割しているのでそれ以前は無事）。

## API送信

カメラ入力かつ `.env` の `API_ENABLED=true` のとき、検出した入出庫を
[tracking-parking-api](https://github.com/NUTFes/tracking-parking-api) へ
リアルタイムに送信する。動画ファイル入力では、設定に関わらず常に送信しない
（検証の再実行が本番の駐車台数を壊さないための安全策）。

```bash
uv run python scripts/run_detection.py --camera 0
uv run python scripts/run_detection.py --camera 0 --no-api  # .envを書き換えずに送信だけ止める
```

設定キーの一覧は `.env.template` を参照。詳細（失敗時の再送方針、集計開始/停止コマンドの扱いなど）は
[docs/decisions/0002-api-event-delivery.md](docs/decisions/0002-api-event-delivery.md) と
[docs/two-line-system.md](docs/two-line-system.md#api送信設定) を参照。

実物のAPI相手にローカルで疎通確認する手順は
[docs/api-verification.md](docs/api-verification.md) を参照
（`scripts/check_api_connection.py` を使う。本番環境には触れない）。

## テスト

```bash
uv run pytest -q          # 開発機
.venv/bin/python -m pytest -q   # エッジ機
```

## ディレクトリ構成

| パス | 役割 |
|---|---|
| `scripts/` | CLIエントリポイント（`run_production.sh` / `setup_production_lines.sh` は実機運用用） |
| `src/tracking_parking/` | 本体パッケージ（検知ロジック、出力、共通基盤、評価） |
| `tests/` | テスト |
| `docs/` | 設計・検証・決定の記録 |
| `plate_recognition/` | ナンバープレート認識 |
| `training/` | YOLOのファインチューニング |
| `view/` | フロントエンド（Next.js） |
| `data/`, `models/` | 入出力データとモデル重み（Git管理外） |

詳細は [docs/two-line-system.md](docs/two-line-system.md) にある。

## ドキュメント

- [docs/two-line-system.md](docs/two-line-system.md) — システム構成、設定パラメータ、アルゴリズム
- [docs/verification.md](docs/verification.md) — 実動画1本での検証手順
- [docs/api-verification.md](docs/api-verification.md) — API送信機能のローカル疎通確認手順
- [docs/system-count-operation.md](docs/system-count-operation.md) — 稼働開始時に `system_count` を実測台数へ合わせる手順
- [docs/wandb_integration_spec_v2.md](docs/wandb_integration_spec_v2.md) — 実験記録（W&B連携）の仕様
- [docs/decisions/](docs/decisions/) — 設計上の決定記録

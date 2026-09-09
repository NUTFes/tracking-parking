# tracking-parking

駐車場の入出庫を検知し、駐車台数を管理するシステム。

車両の検知には**2ライン方式**を採用している。出入口側の `Line1` を主判定ライン、
奥側の `Line2` を補助判定ラインとして、YOLOv8のトラッキング結果からライン通過を
検知し、入庫・出庫をカウントする。方式選定の経緯は
[docs/decisions/0001-two-line-method.md](docs/decisions/0001-two-line-method.md) を参照。

プロジェクト全体の背景は [Wiki](https://github.com/NUTFes/tracking-parking/wiki) にある。

## セットアップ

```bash
uv sync
```

`src/tracking_parking` がeditable installされ、`import tracking_parking` が使えるようになる。

続いて設定ファイルとモデル重み、入力動画を用意する。いずれもGit管理外。

```bash
cp .env.template .env          # HOME_DIR と MODEL_PATH を環境に合わせる
mkdir -p models data/inputs    # models/ に .pt を、data/inputs/ に動画を置く
```

## 使い方

```bash
# 1. GUIでライン座標を設定する（動画の先頭フレームに5点クリック）
uv run python scripts/setup_lines.py --video data/inputs/test.mp4

# 2. 動画を処理して入出庫をカウントする
uv run python scripts/run_detection.py --input data/inputs/test.mp4

# 3. ライン位置と車両代表点の関係を確認する
uv run python scripts/visualize_lines.py data/inputs/test.mp4

# 4. 複数動画をまとめて処理し、サマリーへ集約する
uv run python scripts/run_multi_video.py
```

結果は `data/outputs/` に出る（アノテーション動画、イベントログのJSON/CSV、run manifest）。

## テスト

```bash
uv run pytest -q
```

## ディレクトリ構成

| パス | 役割 |
|---|---|
| `scripts/` | CLIエントリポイント |
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
- [docs/wandb_integration_spec_v2.md](docs/wandb_integration_spec_v2.md) — 実験記録（W&B連携）の仕様
- [docs/decisions/](docs/decisions/) — 設計上の決定記録

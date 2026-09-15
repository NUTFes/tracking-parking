# API送信機能 ローカル検証手順

`src/tracking_parking/api/` の送信機能が、実物の
[tracking-parking-api](https://github.com/NUTFes/tracking-parking-api) と
実際にHTTPで話せることを確認する手順。`tests/api/` の単体テストはすべて手書きの
フェイク相手に検証しており、ヘッダ名・URL・フィールド名・応答の形が実物と一致して
いることは検証していない。ここでの検証はそのギャップを埋める。

実施は [tracking-parking-center](https://github.com/NUTFes/tracking-parking-center)
が提供するローカル開発スタック上で行う。本番環境には一切触れない。カメラ実機を
使った通し確認（Jetson設置時）は対象外。

## 前提

- `tracking-parking-center` と `tracking-parking-api` を同じ親ディレクトリへclone済みであること
- Docker Desktopが起動していること

## 1. 受信側スタックの起動

```bash
cd tracking-parking-center
mkdir -p services
ln -s ../../tracking-parking-api services/api
cp .env.develop.example .env.develop
docker compose --env-file .env.develop up --build db api
```

`api` の起動コマンドに `alembic upgrade head` が含まれるため、`request_id` カラムを
追加するマイグレーションは自動で当たる。

```bash
curl -s http://localhost:8000/api/v1/health
```

デバイスAPIキーの取得（Googleログイン不要。既存の駐車場・デバイスを全削除する
破壊的スクリプトだが、ローカル専用なので問題ない）:

```bash
docker compose --env-file .env.develop exec api python scripts/seed_demo_data.py
# → Device API key (shown once, save it now): xxxx
```

## 2. エッジ側の設定

リポジトリルートの `.env`（Git管理外）へ追記する。

```bash
API_ENABLED=true
API_BASE_URL=http://localhost:8000/api/v1
DEVICE_API_KEY=<seedが出したキー>
API_CONNECT_TIMEOUT_SEC=3.0
API_READ_TIMEOUT_SEC=5.0
HEARTBEAT_INTERVAL_SEC=30
SHUTDOWN_FLUSH_SEC=10
SPOOL_PATH=data/outputs/unsent_events.jsonl
```

## 3. `scripts/check_api_connection.py`

`run_detection.py` を経由せず、`ApiClient` / `EventSender` / `HeartbeatAgent` を
実物のAPI相手に直接動かす検証ドライバ。カメラも動画もモデル重みも要らない。

```bash
uv run python scripts/check_api_connection.py health
uv run python scripts/check_api_connection.py event
uv run python scripts/check_api_connection.py idempotency
uv run python scripts/check_api_connection.py heartbeat
uv run python scripts/check_api_connection.py sender --count 5
```

`API_BASE_URL` のホストが `localhost` / `127.0.0.1` 以外を指しているときは安全のため
実行を拒否する（`--i-know-this-is-not-local` で解除可能。通常は使わない）。

## 4. 契約の確認

- `event`: 202 Acceptedが返り、応答bodyの `request_id` が送った値と一致すること。
  `EventCreate` に `model_config` が無く Pydantic の既定 `extra='ignore'` が効くため、
  フィールド名が1文字でもずれていれば黙って無視される。応答に返ってくるかどうかが
  唯一の検出手段
- `DEVICE_API_KEY` を壊すと401→**DROP**に分類され、再送されないこと
- `heartbeat`: `devices.last_seen_at` が更新されること
- コマンド往復はDBへ直接INSERTして確認する:

  ```sql
  INSERT INTO device_commands (device_id, command_type, status, requested_by, created_at)
  VALUES (1, 'stop_counting', 'pending', 'verification', NOW());
  ```

  直後に `heartbeat` を1回実行し、コマンドが `pending`→`delivered`→`completed`
  （`restart`は`failed`＋理由）まで進むことを確認する。

  **`device_commands.command_type` はMySQLの `ENUM('restart','start_counting',
  'stop_counting')` で、SQLAlchemy側（`app/models/command.py`）も同じ3値の
  Pythonレベルenumで固定されている。** ENUM外の値を直接INSERTすることは通常
  できず、無理にENUMを拡張してから投入すると、**そのデバイスの以後のハートビート
  全てが500になる**（`list_pending_for_device` がその行を読もうとして
  `LookupError` を出す）。エージェント側はこの500を `Disposition.UNKNOWN` として
  ログするだけでスレッドは落ちない（実地確認済み）ので、これはエッジ側の頑健性を
  損なわないが、API側の頑健性の課題として別途報告する。

## 5. べき等の確認

```bash
uv run python scripts/check_api_connection.py idempotency
```

**`POST /events` は202 Acceptedを返し、`system_count` への反映はバックグラウンド
キュー処理に回る（同期しない）。** 2回のPOSTが返った直後に `system_count` を読むと
まだ反映前で「動いていない」ように見えることがある。次で `processed` になるまで
ポーリングしてから判定すること（キュー処理間隔30秒・stale判定60秒なので、
上限90秒程度を見ておく）。

```bash
watch -n3 "curl -s localhost:8000/api/v1/parking-lots | jq '.[] | select(.name==\"講義棟北2\")'"
```

`uuid4().hex`（ダッシュ無し32桁）で送ると、DBには36桁ダッシュ付きへ正規化されて
保存される。2回目も同じhexで正しく一致判定される。

## 6. 障害時の退避と再送

```bash
# 接続拒否（RETRY）を作る
docker compose --env-file .env.develop stop api
uv run python scripts/check_api_connection.py sender --count 3
docker compose --env-file .env.develop start api
uv run python scripts/check_api_connection.py sender --count 0   # 起動時replay

# 応答なし（UNKNOWN）を作る
docker compose --env-file .env.develop pause api
uv run python scripts/check_api_connection.py sender --count 2
docker compose --env-file .env.develop unpause api
uv run python scripts/check_api_connection.py sender --count 0
```

`sender --count 0` はenqueueせずに起動時の `replay_spool()` だけを走らせる。

**`SHUTDOWN_FLUSH_SEC`（既定10秒）は複数イベントが同時に詰まった場合の
バックオフ合計（最大 `1+2+4=7秒/件`）に対して余裕が少ない。** 3件連続で
接続拒否させると、1件目だけが3回のバックオフを使い切って `retry` として
スプールへ落ち、残り2件はflush期限に間に合わず `unknown`（`shutdown: flush期限
までに決着しなかった`）として落ちる。**動作としては設計通り**（キューに残った
ものを結果不明として退避する）だが、実機で複数イベントが同時に滞留する運用が
多いなら `SHUTDOWN_FLUSH_SEC` を長めに見直す余地がある。

いずれの場合も `request_id` が保持されたままスプールへ落ち、復帰後の
`sender --count 0` で全件再送され、`system_count` は送った件数の増減分だけ動く
（二重計上しない）ことを確認する。

## 7. 送信ガード

`run_detection.py` 本体を使う唯一の検証。GTが `in=55` の動画を使い、失敗が
一目でわかる構成にする。

**`--env` はそのファイルだけを読む（`Config.from_env(args.env)`）ため、
`API_ENABLED` を含まない `.env` を `--env` で渡してもガードは検証にならない
（設定が存在せず、ガードは自明に無効側で通ってしまう）。** `load_dotenv` は
既存の環境変数を上書きしないので、インラインの環境変数で与える。

```bash
API_ENABLED=true \
API_BASE_URL=http://localhost:8000/api/v1 \
DEVICE_API_KEY=<key> \
uv run python scripts/run_detection.py \
  --input data/inputs/1787008160.558032.mp4 --env newcam.env
```

事前に `seed_demo_data.py` を実行して `system_count` を0へ戻しておく。

確認項目:

- 起動ログに `✓ API送信を有効化` が出ないこと
- 検知ログ（`[Frame ...] ID:... IN`）が実際に出ていること（ガードが「そもそも
  何も検知していないだけ」ではなく、検知は起きた上で送信だけ止まっていることを
  確認するため）
- 処理後（または `Ctrl+C` で途中終了しても）`parking_events` の行数と
  `system_count` が変化していないこと
- スプールファイルが作られていないこと

`Ctrl+C`（`SIGINT`）は `finally` 節を通るため、動画全体を処理し終えなくても
早期に打ち切って確認できる。

# 実験管理機能（Weights & Biases 連携）実装指示書 v2

> v1 からの主な変更: オフラインモード対応（§1-8, §6）、スイープ時のトラッカー状態リセット（§4.2）、
> フレームログのダウンサンプリング（§2.3）、異常終了時の finish 保証（§3.1）、`exp_key` 生成規則の一元化（§3.1）、
> 共通モジュールの import 経路指定（§3.3）、W&B Artifact のオプション項目追加（§10）。
>
> このドキュメントは git 管理下の正式な契約書である（Issue #102 にて .gitignore の docs/ 一括除外に例外を追加し追跡開始）。
> 実装との乖離が見つかった場合は、実装かこのドキュメントのどちらかを速やかに追随させること。

## 0. このドキュメントの目的

`raspi/` 配下の駐車場入出庫カウントシステムに、Weights & Biases（以下 W&B）による実験管理機能を追加する。
本システムには検出ロジックが 2 系統あり、両者の **性能比較** と、本番デバイス上での **処理速度管理** を目的とする。

- `line_detection/` … 2 ライン + 外積法 + ハイブリッド方式（信頼度付き）
- `roi-counter/` … ROI 内の進行度 `s` による状態機械

精度指標（Accuracy / Precision / Recall / F1）は **SAM3 による GT を用いて後日別スクリプトで算出する**ため、本実装では「速度・台数の即時記録」と「精度を後から同一 run へ追記できる仕組み」を分けて作る。

---

## 1. 設計の大原則（必ず守ること）

1. **記録粒度を 3 層に分ける。**
   - `config`（run 開始時に固定するスカラ設定）
   - `summary`（run 終了時の単一スカラ結果）
   - `time-series`（フレーム / イベントごとの `wandb.log(step=...)`）
2. **比較したくなりそうな軸は、値が未定でも config キーとして必ず用意する**（未使用なら既定値か `None`）。config に無い軸は後から比較できない。
3. **精度系の summary キーは、データが無くても `None` で先に確保する**。後追いスクリプトが同じスキーマへ書き込めるようにするため。
   - 注意: W&B のテーブル UI では値が全 run で `None` の間は列が表示されないことがあるが、キー自体は保存されるので問題ない。後追い書き込み後に列が現れる。
4. **run を一意に再特定できる手段を 2 重で持たせる。**
   - `run.id` を出力ディレクトリ内のファイルに保存する。
   - `config` に複合キー `exp_key`（生成規則は §3.1 で一元化）を必ず埋め、run.id を取りこぼしても突合できるようにする。
5. **時系列メトリクスは後から遡及追加できない**。最初に `wandb.log` する辞書へ余分めにキーを用意しておく。スカラ（summary / config）は後付け可。
6. 既存スクリプトの**コア処理ロジック（検出・カウント・MAE 算出）は原則変更しない**。W&B 連携は addon として差し込む。
   - **唯一の例外**: §4.2 のトラッカー状態リセット。これは実験の独立性（run 比較の妥当性）に直結するため修正を許可する。
7. **W&B を無効化できるフラグ**（`USE_WANDB` / 環境変数）を用意し、オフ時は既存挙動と完全に一致させる。CI やオフライン実行で壊れないこと。
   - 「既存挙動と完全一致」の具体的な意味: JSON/CSV の**キー集合・列集合・列順序**が W&B 導入前と完全に一致すること。
     `02_run_analysis.py` の `result.json` は元々この条件を満たす（`append_to_result_json` は無効時 no-op）。
     `04_multi_video_mae.py` の `results.csv` は Issue #102 で修正: `wandb_run_id` / `exp_key` 列は `USE_WANDB=true` のときのみ追加する。
8. **ネットワークの無い環境（Raspberry Pi 実機）での計測を第一級ユースケースとする。**
   - `WANDB_MODE` 環境変数（`online` / `offline`）を尊重する。offline 時はローカルに記録され、後日 `wandb sync` でアップロードできる。
   - README（または各スクリプトの docstring）に offline 計測 → sync の手順を 3〜4 行で記載すること。

---

## 2. 記録する情報の定義

### 2.1 config（run 開始時に固定）

| キー | 型 | 説明 | 取得元 |
|---|---|---|---|
| `logic_name` | str | 検出ロジック名。`"line_detection"` または `"roi_counter"` | スクリプト側で固定指定 |
| `dataset` | str | 対象データ名（動画 stem 等） | `VIDEO_SOURCE` から導出 |
| `input_type` | str | `"file"` or `"camera"` | `VIDEO_SOURCE` の型で判定 |
| `device_name` | str | 処理デバイス名（例 `"raspi5"`, `"macbook_m1"`） | 環境変数 `EXP_DEVICE_NAME`（未設定なら `platform.node()` をフォールバック） |
| `device_accelerator` | str | `"cpu"` / `"cuda"` / `"coral"` 等 | 環境変数 or 自動判定 |
| `model_path` | str | 使用した重みファイル名 | 各スクリプトのモデル指定 |
| `frame_width` | int | 入力解像度 幅 | `cv2.CAP_PROP_FRAME_WIDTH` |
| `frame_height` | int | 入力解像度 高さ | `cv2.CAP_PROP_FRAME_HEIGHT` |
| `source_fps` | float | 入力動画の FPS | `cv2.CAP_PROP_FPS` |
| `vehicle_classes` | list | 検出対象クラス | 各スクリプト |
| `tracker_reset` | bool | run 開始時にトラッカー状態をリセットしたか（§4.2 参照） | スクリプト |
| `log_interval_sec` | float | 時系列ログの間引き間隔（秒、相対経過時間ベース）。0 以下・NaN・inf は起動時にエラー（§2.3 参照） | 環境変数 `LOG_INTERVAL_SEC`（既定 5 秒） |
| **YOLO config** | | | |
| `yolo_conf` | float | confidence_threshold | `model.track()` に実際に渡した値と完全一致させる（記録専用の別定数を持たせてはならない） |
| `yolo_iou` | float | iou_threshold | `model.track()` に実際に渡した値と完全一致させる（記録専用の別定数を持たせてはならない） |
| `yolo_device` | str/None | model.track() に渡す device 指定 | 環境変数 `YOLO_DEVICE`（既定 None＝Ultralytics 自動選択） |
| **ロジック別パラメータ** | | | |
| `s_low` / `s_high` | float | roi-counter の閾値 | roi-counter のみ |
| `margin` / `max_frame_gap` / `cleanup_threshold` | num | line_detection のパラメータ | line_detection のみ |
| **複合キー（突合用・必須）** | | | |
| `exp_key` | str | §3.1 の `build_exp_key()` で生成 | 共通ユーティリティ |

### 2.2 summary（run 終了時のスカラ）

| キー | 型 | 説明 | この実装で値を入れるか |
|---|---|---|---|
| `count_in` | int | 入庫数 | ○ |
| `count_out` | int | 出庫数 | ○ |
| `total_frames` | int | 総フレーム数 | ○ |
| `total_ms` | float | 総処理時間 | ○ |
| `frame_ms_mean` | float | 1 フレーム平均処理時間 | ○ |
| `frame_ms_min` | float | 最速 | ○ |
| `frame_ms_max` | float | 最遅 | ○ |
| `frame_ms_p50` | float | 中央値 | ○ |
| `frame_ms_p95` | float | p95（本番カクつき評価用） | ○ |
| `frame_ms_p99` | float | p99 | ○ |
| `effective_fps` | float | `1000 / frame_ms_mean` | ○ |
| `realtime_ok` | bool | `effective_fps >= source_fps` | ○ |
| `count_error` | int/None | `|in-gt_in| + |out-gt_out|`（GT があれば） | △（GT 次第） |
| `gt_in` / `gt_out` | int/None | 台数の真値 | △ |
| **精度系（後追いで埋める。今は None で確保）** | | | |
| `accuracy` | float/None | | × → `None` |
| `precision` | float/None | | × → `None` |
| `recall` | float/None | | × → `None` |
| `f1` | float/None | | × → `None` |
| `tp` / `fp` / `fn` / `tn` | int/None | 混同行列の素値 | × → `None` |
| `eval_unit` | str/None | `"event"` or `"detection"`（評価単位） | × → `None` |
| `gt_source` | str/None | `"sam3"` / `"manual"` 等 | × → `None` |

### 2.3 time-series（`wandb.log(step=frame_idx)`）

| キー | 説明 |
|---|---|
| `frame_ms` | そのフレームの処理時間 |
| `net_flow` | `count_in - count_out` の逐次値（初期駐車台数の絶対値ではなく、あくまで純増減 = net flow） |
| `cumulative_in` | 累積入庫数 |
| `cumulative_out` | 累積出庫数 |
| `num_tracks` | そのフレームで新たにトラッカー ID が割り当てられた検出数（`len(boxes.id)`、無ければ 0）。ROI フィルタ前の値。 |
| `retained_states` | 状態保持ストアのサイズ（roi-counter: `len(counter.tracks)`）。`num_tracks` とは意味が異なる（前者はフレーム単位の新規検出数、後者は累積して保持されている track 状態の総数）ため混同しないこと。 |

**間引き（必須要件）**: 毎フレーム log すると長時間のカメラ運用で呼び出し回数・帯域が肥大するため、`log_interval_sec`（秒単位、データセット内の相対経過時間 `t_rel_sec` ベース）でサンプリングする。

- 既定値: 5 秒（環境変数 `LOG_INTERVAL_SEC` で上書き可）。0 以下・NaN・inf は起動時に検証エラーとし、フェイルファストする（`common.wandb_logger.validate_log_interval_sec` で検証）。
- 間引き中でも **カウントが変化したフレーム（IN/OUT イベント発生時）は必ず log する**（駐車台数推移の階段が欠けないようにするため）。この強制ログは次回の定期サンプリング境界の計算には影響しない（境界はあくまで `t_rel_sec` のみから算出される）。
- `step` には常に実フレーム番号 `frame_idx` を使う。x 軸（`step_metric`）は `t_rel_sec`（データセット内の相対経過秒）。
- 境界計算は while ループではなく除算による O(1) 計算で行う（`common.wandb_logger.next_log_boundary`）。フレーム抜け等で `t_rel_sec` が複数区間分ジャンプしても、1 回の計算で正しい次境界に到達する。

---

## 3. 実装するモジュール

### 3.1 共通ユーティリティ `raspi/common/wandb_logger.py`（新規作成）

両ロジックから共有する薄いラッパを作る。W&B 無効時は no-op になること。

要件:

- `class ExperimentLogger` を定義する。
- `__init__(self, project: str, config: dict, group: str, job_type: str, tags: list, enabled: bool)`
  - `enabled=False` のとき `wandb.init` を呼ばず、以降の全メソッドを no-op にする。
  - `wandb.init(project=..., config=config, group=group, job_type=job_type, tags=tags)` を実行。
  - `WANDB_MODE` は wandb 側の標準挙動に任せる（本ラッパで上書きしない）。
- `log_frame(self, step: int, metrics: dict)` … `wandb.log(metrics, step=step)`。
- `set_summary(self, key: str, value)` / `set_summaries(self, d: dict)`。
- `finish(self, exit_code: int = 0)` … `wandb.finish(exit_code=exit_code)`。
- **`run_id` プロパティ** … `wandb.run.id`（無効時は `None`）。
- `save_run_id(self, out_dir: Path)` … `out_dir / "wandb_run_id.txt"` に run.id と exp_key を書き出す。既存の `result.json` がある場合はそこへ `wandb_run_id` / `exp_key` を追記できるヘルパも用意。
- `init_accuracy_placeholders(self)` … §2.2 の精度系キーを `None` で summary に設定。init 直後に呼ぶ。
- **`build_exp_key(logic_name: str, dataset: str, device_name: str, params: dict) -> str`（モジュール関数）**
  - 形式: `f"{logic_name}__{dataset}__{param_str}__{device_name}"`
  - `param_str` は `params` を **キー名の昇順ソート**で `"k1=v1_k2=v2"` に正規化する（float は `f"{v:g}"`）。
  - この関数を両ロジック・後追い評価スクリプトの**全員が共通で使う**こと。各スクリプトで独自フォーマットを組み立ててはならない（突合キーとして機能しなくなるため）。
- `validate_log_interval_sec(value: float, source: str = "LOG_INTERVAL_SEC") -> float`（モジュール関数）… 0 以下・NaN・inf・不正文字列を拒否し `ValueError` を送出する。起動時に呼ぶこと。
- `next_log_boundary(next_log_sec, t_rel_sec, log_interval_sec) -> float` / `should_log_frame(t_rel_sec, next_log_sec, count_changed) -> bool`（モジュール関数）… 定期サンプリング境界の判定・進行を while ループなしで行う。

実装メモ:
- `wandb` の import は遅延 import（`enabled` のときだけ）にして、未インストール環境で読み込み自体が落ちないようにする。
- **呼び出し側は `finish()` を必ず `try/finally` で保証する**（§4 各所に明記）。カメラ切断・例外・Ctrl+C でも run が "running" のまま放置されないこと。異常終了時は `exit_code=1` で finish する。
- 長時間のカメラ運用向けに `update_running_summary(self, d: dict)`（処理途中の count_in/out 等を summary へ随時反映するだけの薄いメソッド）を用意する。クラッシュしても直近の集計が残る。

### 3.2 統計ユーティリティ `raspi/common/frame_stats.py`（新規作成）

- `compute_frame_stats(frame_ms_list: list[float], source_fps: float) -> dict`
  - min / max / mean / p50 / p95 / p99 / total_ms / effective_fps / realtime_ok を返す。
  - 空リスト時は全て 0 または `False` を返し例外を出さない。
- `numpy` を使ってよい（既存依存にあり）。

### 3.3 共通モジュールの import 経路（重要・未指定だと迷う）

両プロジェクトは既に `sys.path.insert(0, <自ルート>)` スタイルなので、これに合わせる。パッケージ化（pip install -e）は今回しない。

- `raspi/common/__init__.py` を作成する。
- 各スクリプトの既存 `sys.path.insert` の直後に、`raspi/` ディレクトリも追加する:
  ```python
  # 例: raspi/roi-counter/scripts/02_run_analysis.py の場合
  sys.path.insert(0, str(Path(__file__).parents[1]))   # 既存: roi-counter/
  sys.path.insert(0, str(Path(__file__).parents[2]))   # 追加: raspi/
  from common.wandb_logger import ExperimentLogger, build_exp_key
  from common.frame_stats import compute_frame_stats
  ```
- `line_detection/main.py` は `os.path.dirname` スタイルなのでそれに合わせて親ディレクトリを追加する。

---

## 4. 既存スクリプトへの差し込み

### 4.1 `roi-counter/scripts/02_run_analysis.py`

- 冒頭パラメータ群の近くに W&B 設定（`USE_WANDB`, `WANDB_PROJECT`, `EXP_DEVICE_NAME`, `LOG_INTERVAL_SEC` 等）を追加。環境変数で上書き可能にする。
- `main()` 内:
  1. 既存の `out_dir` 作成後、`config` dict を構築（§2.1 に従う。`logic_name="roi_counter"`, `s_low/s_high` を含める）。
  2. `build_exp_key()` で `exp_key` を生成し config に入れる。
  3. `ExperimentLogger` を初期化し、`init_accuracy_placeholders()` を呼ぶ。**以降の処理全体を `try/finally` で包み、finally で `finish()`**（例外時は `exit_code=1`）。
  4. フレームループ内、既存の `frame_records.append(...)` の直後に、間引き条件（§2.3）を満たすフレームで `logger.log_frame(step=frame_idx, metrics={...})` を追加（`frame_ms`, `net_flow`, `cumulative_in`, `cumulative_out`, `num_tracks`, `retained_states`）。カウント変化時は間引き中でも log。
  5. ループ後、`compute_frame_stats()` の結果と count 系を `set_summaries`。GT があれば `count_error` も。
  6. `logger.save_run_id(out_dir)` と `result.json` への `wandb_run_id` / `exp_key` 追記。
- **既存の CSV / JSON / mp4 出力は一切削らない**。

### 4.2 `roi-counter/scripts/04_multi_video_mae.py`（スイープ）

- **(s_low, s_high, video) の組ごとに 1 run** を作る。時系列 log は行わず、config + summary のみ（run 数 × フレーム数の log は過剰なため）。
- `run_once()` の戻り値に `frame_times`（生リスト）を含めるよう拡張（p95 等の算出に必要）。
- **【既存バグ修正・原則 6 の例外】トラッカー状態のリセット**:
  - 現状は同一 `YOLO` インスタンスを `persist=True` のまま全組で使い回しており、**前の run のトラック ID 状態が次の run に持ち越される**。これでは run が独立でなく、W&B 上の比較が成立しない。
  - `run_once()` の冒頭でトラッカー状態をリセットすること。実装は次の優先順で試す:
    1. `model.predictor.trackers[0].reset()`（ultralytics のバージョンにより利用可否が変わるため、`hasattr` チェックの上で呼ぶ）
    2. 上記が使えない場合は `YOLO(MODEL_PATH)` を run_once ごとに再生成する（ロード時間は増えるが正しさを優先）。
  - どちらを行ったかに関わらず `config["tracker_reset"] = True` を記録する。リセットできなかった場合は `False` を記録し WARN を出す。
  - 同じ問題は `03_sweep_params.py` にもあるが、本実装のスコープは 04 のみとし、03 は TODO コメントを残す。
- `main()` のループ内、`run_once` の後で run を 1 つ作り、config・summary（速度統計 + count + count_error + gt）・精度プレースホルダを記録して finish（try/finally）。
- `detail_rows`（既存 CSV）に `wandb_run_id` / `exp_key` 列を追加して CSV と W&B を相互参照可能にする。
- 既存の `results.csv` / `mae_summary.csv` 出力は維持する。

### 4.3 `line_detection/main.py`

- `process_video()` に W&B 連携を追加。
- `config` は `logic_name="line_detection"`, `margin`, `max_frame_gap`, `cleanup_threshold`, `yolo_conf`, `yolo_iou`, `model_path`, 解像度, fps 等。
- **処理時間の生リストは `process_video()` 内のローカルリストで保持する**（`EventLogger` クラスは変更しない。processing_time_ms を計算している箇所で同じ値を append するだけ）。
- フレームループで間引き付き `log_frame`。`net_flow` は `tracker.get_net_flow()` 相当の値（`count_in - count_out`）、`num_tracks` はそのフレームで新たにIDが割り当てられた検出数、`retained_states` は `len(tracker.states)`（保持中の状態数、num_tracksとは別概念）。カウント確定時（`mark_as_counted` が呼ばれたフレーム）は間引き中でも log。
- カメラ入力（`--camera`）は長時間運用になるため、`update_running_summary()` を N フレームごと（例: 300 フレーム）に呼び、クラッシュ時にも直近カウントが summary に残るようにする。
- ループ後、`tracker.get_summary()` とローカル処理時間リストから summary を構築。全体を try/finally で包み finish を保証（既存の KeyboardInterrupt ハンドリングと整合させる）。
- 既存の `EventLogger`（JSON/CSV 出力）は維持。`events_*.json` に `wandb_run_id` / `exp_key` を含める（`EventLogger.save_json` の data dict へ引数追加で渡す。デフォルト `None` にして後方互換を保つ）。
- `argparse` に `--wandb` / `--device-name` を追加してよい。

---

## 5. 後追い精度評価スクリプト `raspi/eval/update_accuracy_from_sam3.py`（新規作成・雛形のみ）

SAM3 の GT が揃った後に実行する独立スクリプト。**run の再開ではなく W&B API 経由で既存 run の summary を更新する**方針（実行と評価を分離するため）。

要件:

- 入力: SAM3 由来の評価結果テーブル（per-run の accuracy / precision / recall / f1 / tp/fp/fn/tn と、対応する `exp_key` または `wandb_run_id`。CSV か JSON）。
- 処理:
  1. `wandb.Api()` を使う。
  2. 各評価行について、`wandb_run_id` があればそれで run を直接取得。無ければ project 内の run を `config.exp_key` 一致で検索（`api.runs(path, filters={"config.exp_key": key})` を使う。全走査は避ける）。
  3. `run.summary["accuracy"] = ...` 等を設定し、`run.summary.update()`。
  4. `eval_unit` / `gt_source="sam3"` も記録。
  5. 一致する run が 0 件 / 複数件の場合は WARN を出してスキップ（複数件は最新 run を選ぶのではなく人間に判断させる）。
- **GT の定義を明示するコメントを必ず書く**:
  - 台数の最終 GT は人手の真値（既存 `*_gt.json`）を ground truth とする。
  - SAM3 は per-vehicle 軌跡 / イベント列の生成補助に使い、SAM3 出力をそのまま GT としない。
  - 評価単位（`event` / `detection`）はスクリプト冒頭の定数で選択。デフォルトは `event`。
- マッチングロジック本体は TODO コメントで枠だけ作る（GT データが無いため）。インターフェース（入力フォーマット、出力 summary キー）だけ確定させる。
- **ダミー入力での動作確認用に、`--dry-run` フラグ**（対象 run と書き込み予定値を表示するだけで書き込まない）を実装する。

---

## 6. W&B プロジェクト構成の指針（コメントとして残す）

- `project`: 単一プロジェクト（例 `"tracking-parking"`）。
- `group`: `logic_name`。 `job_type`: `"speed_eval"` / `"accuracy_eval"`。 `tags`: `device_name`, `input_type`。
- 1 run = (logic × dataset × params × device) の 1 実行。
- **オフライン運用**: Raspberry Pi 実機ではネットワークが無い前提で `WANDB_MODE=offline` で実行し、後日開発機で `wandb sync <run_dir>` する。手順を README に記載。

---

## 7. 受け入れ条件（Definition of Done）

1. `USE_WANDB=false` で全スクリプトが従来どおり動作し、出力ファイルが変わらない（`wandb` 未インストールでも動く）。
2. `USE_WANDB=true` で各 run に config / summary / time-series が記録される。
3. 全 run の config に `exp_key` が入り、`build_exp_key()` が全スクリプトで共有されている。出力ディレクトリに `wandb_run_id` が保存される。
4. summary に精度系キーが `None` で存在する。
5. `update_accuracy_from_sam3.py --dry-run` が、ダミー評価テーブルを入力に対象 run を正しく特定・表示できる。dry-run なしで summary 更新が動作する。
6. `frame_ms_p95` / `effective_fps` / `realtime_ok` が正しく算出される（`compute_frame_stats` の単体テストで担保）。
7. 例外・KeyboardInterrupt で中断しても run が finish される（手動確認でよい）。
8. `04_multi_video_mae.py` で run 間のトラッカー状態リセットが行われ、`tracker_reset` が config に記録される。
9. `LOG_INTERVAL_SEC` の間引きが機能し、カウント変化フレームは間引き中でも log される。
10. 既存テスト（`roi-counter/tests/`）が引き続き通る。`raspi/common/tests/` に `frame_stats` と `ExperimentLogger`（enabled=False の no-op、build_exp_key の正規化）の最小テストを追加する。

---

## 8. 依存関係

- `wandb` を `requirements.txt` / `pyproject.toml` に追加（最新安定版を指定）。
- `wandb` 未インストールでも `USE_WANDB=false` 経路は動くこと（遅延 import）。

---

## 9. 実装順序の推奨

1. `common/frame_stats.py` と `common/wandb_logger.py`（no-op 経路・build_exp_key・テスト含む）。
2. `roi-counter/scripts/02_run_analysis.py` への差し込み（最小構成の検証）。
3. `roi-counter/scripts/04_multi_video_mae.py`（スイープ → 複数 run、トラッカーリセット含む）。
4. `line_detection/main.py`。
5. `eval/update_accuracy_from_sam3.py`（雛形 + dry-run）。
6. requirements 更新・README への offline 手順追記。

---

## 10. オプション（余力があれば。必須ではない）

- **W&B Artifact**: run 終了時に `vehicles.csv`（roi-counter）/ `events_*.json`（line_detection）を artifact としてアップロードする。per-vehicle の誤検出分析を run 間で見比べられるようになる。offline モードでも artifact はローカル保存され sync 時に上がる。
- **W&B Table**: `vehicles.csv` の内容を `wandb.Table` として log し、UI 上で track_id ごとの counted_as / state をフィルタ可能にする。
- どちらも `enabled` フラグとは別のオプトイン設定（`WANDB_UPLOAD_ARTIFACTS=true`）で制御する。

# 2026-09-20 実機運用の記録

エッジ機（Jetson Orin NX）で 08:13〜17:18 を通して運用した記録。
[runbook](production-runbook.md) の手順で動かし、[9/19 の記録](operation-report-20260919.md)
で残作業になっていた「カメラの固定強化」「ライン座標の取り直し」を実施したうえでの通し運用。

結論を先に書く。

- **画角は一度も動かなかった。** 9/19 の最大の運用リスクは解消された
- **デバイスの集計は最後まで厳密に整合した。** 開始時 `system_count=7` に対し
  入庫480 / 出庫388 で、停止時のサーバー値は `7 + 92 = 99`。イベント868件すべてが
  送信され、取りこぼしも二重計上もゼロ
- ただし **夕方の出庫ラッシュで人力集計と62台乖離した。** 日中は差1で一致していた。
  実台数は人力側（161）と判断しており、**デバイスが出庫を過剰計上していた**ことになる
- **`system_count` に上限クランプは無い**ことを受信側のコードで確認した（満車でも入庫は捨てられない）

## 当日の run

| # | 時間 | 録画 | 入庫 | 出庫 | 備考 |
|---|---|---|---|---|---|
| 1 | 08:06–08:12（6分） | 1本・46MB | 0 | 0 | 起動確認。tmux外で起動したため停止して入れ直した |
| 2 | 08:13–17:18（9時間5分） | 17本・4.2GB | 480 | 388 | 本番。処理フレーム 266,370 |

run 1 は動作検証で、カウントには影響していない。記録は
`camera_20260920_080631/` と `events_20260920_080631.*` に残してある。

## 1. tmux の起動事故は `send-keys` を使わなければ構造的に防げる

9/19 の run 2 は `send-keys` でペインに残っていた `ls` と連結し、
`lsSAVE_VIDEO=true scripts/run_production.sh` として起動していた。

**今日も同じ現象を再現した。** 新規セッション作成直後に `send-keys` を送ると、
bash がプロンプトを描画する前に文字がエコーされ、ペインの1行目に打った文字列が
残った状態になる。画面スクレイプでは readline のバッファが綺麗かを断定できない。

```
1:SAVE_VIDEO=true scripts/run_production.shtrapa-dev2@ubuntu:~/workspace/tracking-
2:parking$ SAVE_VIDEO=true scripts/run_production.sh
```

**起動コマンドをペインのプロセスとして直接指定すればタイプ入力が発生しない。**

```bash
tmux new-session -d -s parking -c ~/workspace/tracking-parking \
  'SAVE_VIDEO=true scripts/run_production.sh'
tmux set-window-option -t parking remain-on-exit on
```

`remain-on-exit on` を付けると停止後もペインに終了サマリーが残る。
確認は `tmux capture-pane -p -S -200 -t parking`。

**tmux サーバの親プロセスが `1`（init）であることを確認すること。** これで
起動元のセッション（ターミナル、Claude Code など）から独立する。

```bash
pid=$(pgrep -f "scripts/run_detection.py --camera" | head -1)
while [ -n "$pid" ] && [ "$pid" != "1" ]; do
  ps -o pid=,ppid=,comm= -p "$pid"; pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
done
```

なお `run_production.sh` の事前チェック出力は `tee` より前に出るため
**実行ログファイルには残らない**（`録画: 有効` の行も含む）。ペインの
スクロールバックにしかないので、確認するならそちらを見る。

## 2. `jetson-newcam.env` は git 管理外

`.gitignore` の `*.env` に該当するため **`git checkout` では戻せない。**
ライン座標を取り直す前に必ずファイルごとバックアップを取る。

```bash
cp jetson-newcam.env /tmp/jetson-newcam.env.bak-$(date +%Y%m%d_%H%M%S)
```

今日の取り直しでの変更（08:03:16 保存）。

| | 9/19 08:00 設定 | 9/20 08:03 設定 |
|---|---|---|
| LINE1 | (222,514) → (1168,583) | (1171,639) → (219,607) |
| LINE2 | (957,369) → (1153,548) | (1116,579) → (958,431) |
| PARKING_REF | (1108,413) | (1142,486) |

画角の照合結果（今日のフレーム基準の最良整合）。

| 比較対象 | 最良整合 | 残差MSE |
|---|---|---|
| 9/19 朝 09:54（カメラが動く前） | dx=-60px, dy=0px | 8477 |
| 9/19 夕 17:17（手で戻したあと） | dx=-44px, dy=+12px | 5124 |

**日をまたぐ比較に 9/19 の閾値（先頭4000 / 直前2500）を使ってはいけない。**
平行移動で合わせても残差が5000前後残る。日照と天候の差が支配的なうえ、
カメラの動きは並進ではなく向きの変化のため。閾値が意味を持つのは同一run内だけ。

## 3. 画角は一日を通して動かなかった

同一run内で 9/19 の輝度差分法を適用した結果。

| セグメント | 確定時刻 | 先頭との差 | 直前との差 |
|---|---|---|---|
| segment_00000 | 08:45 | 0 | 0 |
| segment_00002 | 09:49 | 832 | 832 |
| segment_00003 | 10:21 | 1026 | 711 |
| segment_00010 | 14:08 | 847 | — |
| segment_00011 | 14:40 | 962 | 166 |
| segment_00012 | 15:13 | 958 | 168 |
| segment_00013 | 15:45 | 826 | 166 |

閾値（先頭4000 / 直前2500）から大きく離れている。9/19 に実際に動いたときは
9402 / 3147 だった。**9時間の累積でも最大1026** で、日照変化のみの参考値
（9/18 の日没跨ぎで最大1870）より小さい。カメラの固定強化が効いている。

### 稼働中でも画角は確認できる

カメラは1プロセス排他だが、**確定済みセグメントからフレームを抜けば
検知を止めずに画角を確認できる。** `preview_camera.py` を使う必要はない。

```bash
ffmpeg -v error -sseof -2 -i <確定済みセグメント>.mp4 -frames:v 1 -q:v 2 -y out.jpg
```

書き込み中のセグメントは `moov atom not found` で読めないため、常に確定済みの
1つ前を使う。確定間隔は 256MB ごと＝**約32分**（今日の実測は 31〜33分で安定）。

## 4. 人力集計との乖離が夕方に開いた

| 時刻 | `system_count`（デバイス） | `current_count`（人力） | 差 |
|---|---|---|---|
| 10:31 | 200 | 197 | +3 |
| 14:53 | 197 | 198 | −1 |
| 16:15 | 141 | 167 | **−26** |
| 17:18 | 99 | 161 | **−62** |

入庫403件を捌いた 14:53 の時点では差1だった。**開いたのは出庫ラッシュ以降に限られる**
（14:53〜16:15 で +25、16:15〜17:18 で +36 と加速）。

**送信の問題ではない。** スプールは終日0件で、デバイスの内部カウントとサーバーの
`system_count` は常に厳密一致していた（`7 + 480 − 388 = 99`）。検知側の問題である。

実台数は人力側（161）と判断した。したがって**デバイスが出庫を62台ぶん過剰に
計上していた**ことになる。

有力な仮説は、**満車付近で入れなかった車が場内を周回して出ていく**ケース。
入庫は Line2 を横切らないため記録されないが、出ていく際に出庫として数えられる。
今日は人力集計で 197〜198 台（定員200）の満車状態が日中ずっと続いていた。
**未検証。**

## 5. 事後分析にはフレームの焼き込みJSTを使う（イベントログに壁時計時刻が無い）

`events_*.json` のキーは
`track_id / event_type / frame_id / timestamp_sec / confidence / line2_crossed / event_id`
のみで、**壁時計時刻を持たない。** `timestamp_sec` は公称30fpsでフレーム番号を
割った値なので実時刻には変換できない（[ADR 0003](decisions/0003-camera-input-and-recording.md) の既知の課題）。

「16:15〜17:18 の出庫イベント」のような時刻での抽出は、`frame_id` から
セグメントを割り出してフレームの焼き込みJSTを読む手順になる。今日の実効は
約9.7fps なので、`frame_id / 9.7` が起動からの概算秒数になる。

## 6. `system_count` に上限クランプは無い

10:31 時点で `system_count` が `capacity`（200）とちょうど同値になったため、
飽和を疑って受信側の実装を確認した
（[event_usecase.py](https://github.com/NUTFes/tracking-parking-api/blob/main/app/usecases/event_usecase.py)）。

```python
lot.system_count += 1                          # 入庫: 上限クランプなし
lot.system_count = max(0, lot.system_count - 1)  # 出庫: 0で下限クランプ
```

**入庫側にクランプは無い。** 満車でも入庫イベントが静かに捨てられることはなく、
`capacity` と同値になっても飽和ではなく素直な累積値である。

## 7. 起動を先にして直後に `system_count` を合わせてよい

`target: "system"` のリセットは**指定値の代入**なので、起動からリセットまでの間に
何が起きても上書きして正す。runbook の工程2→3 の順序は入れ替えられる。

順序を入れ替えても精度は落ちない。数えている最中の出入りは、どちらの順序でも
`system_count` には反映されないため。**違うのは起動先行なら録画とローカルの
イベントログにその窓が残ること。** 証跡が早く始まるぶん有利。

条件は4つ。

1. **数えるのはリセットの直前。** 起動前に数えた数を後から入れると二重にずれる
2. **窓を短くする。** 実質的なリスクは技術面ではなく「忘れること」
3. **`target: "system"` を確認する。** `"current"` は公開ビューアを書き換える
4. **リセット前にスプールが0であることを確認する。** リセット前に検知された
   イベントがスプール経由でリセット後に届くと、リセット済みの値に加算されて壊れる

## 8. リセットAPIはデバイスAPIキーでは通らない

「コマンドで実測値を送って同期する」案を検討した結果。
`https://api-trapa.nutfes.net/openapi.json` で定義を確認できる。

| エンドポイント | 必要な認証 |
|---|---|
| `POST /parking-lots/{id}/reset` | **`AdminAccessToken`**（Bearer / `/auth/google` 由来） |
| `POST /parking-lots/reset-all` | **`AdminAccessToken`** |
| `POST /parking-lots/{id}/adjust` | `GoogleIdToken`（manager手入力・`current_count` のみ） |
| `POST /events`（Jetsonが使う） | `APIKeyHeader`（`X-API-Key`） |

Jetson の `DEVICE_API_KEY` は `X-API-Key` スキームで、reset とは別系統。
**検知プロセスのついでに絶対値を送る形にはできない。** 受信側が意図的に
分離している境界なので迂回しない。

CLI化する価値は `target` の取り違えをコードで潰せる点にある。実装するなら
トークン取得が課題で、現実的なのは2案。

- **案A**: 機体のブラウザで admin にサインインし、refresh クッキーを cookie jar へ。
  以降は `POST /auth/refresh`（認証不要・クッキーを見る）で短命アクセストークンを
  取り直す。**リフレッシュトークンは使い捨てでローテーションする**ため jar の更新保存が必須
- **案B**: devtools からアクセストークンをコピーし環境変数で渡す（短命・使い捨て）

**Jetson に admin 資格情報を置くリスク**とのトレードオフになる。今日は admin-web で運用した。

## 実測値（2026-09-20、1280x720 / yolov8s / Orin NX）

| 指標 | 実測 |
|---|---|
| スループット | 中央値 103.3ms/フレーム（約9.7fps）。min 93.3 / max 481.5 |
| 温度 | CPU 56.1℃ / GPU 53.6℃（9時間通して上昇なし） |
| 録画容量 | 4.2GB / 9時間（約11GB/日）。256MBで分割し17本 |
| セグメント確定間隔 | 31〜33分 |
| 処理フレーム数 | 266,370 |
| イベント総数 | 868件（入庫480 / 出庫388） |
| 未送信スプール | 終日0件 |

## 停止時の確認（全項目クリア）

```
ユーザーによる中断 → 処理完了!   （finally を通過）
```

| 確認項目 | 結果 |
|---|---|
| 検知プロセス・gst-launch | 残存なし |
| カメラ | 解放済み |
| 録画17本の再生可否 | **正常 17本 / 異常 0本**（全ファイルで moov を確認） |
| イベントログ JSON / CSV | 保存済み |
| 未送信スプール | 0件 |

全セグメントの健全性はこれで確認できる。

```bash
for f in data/outputs/videos/camera_YYYYMMDD_HHMMSS/*.mp4; do
  ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" >/dev/null \
    || echo "NG: $f"
done
```

## 残っている作業

1. **次回起動時に `system_count` を実測台数へリセットする。** 停止時の 99 は
   実態より62台低い。そのまま持ち越すと今日のずれが翌日に残る
2. **出庫の過剰計上62台の原因を特定する。** 14:53 以降の録画（`segment_00011` 以降）を
   追う。満車時の周回車が出庫として数えられている仮説を検証する
3. **`scripts/preview_camera.py` が未コミット。** 画角調整に使えるツールなので
   リポジトリに入れる

## 記録の所在

| 種類 | パス |
|---|---|
| 録画（run 2） | `data/outputs/videos/camera_20260920_081330/`（17本・4.2GB） |
| 録画（run 1） | `data/outputs/videos/camera_20260920_080631/`（1本・46MB） |
| イベントログ | `data/outputs/logs/events_20260920_081330.json` / `.csv` |
| 実行ログ | `data/outputs/run_20260920_081325.log` |
| W&B（offline） | `data/outputs/wandb/offline-run-20260920_081333-2y9l73p9` |

`logs/wandb_run_id.txt` は固定名で毎回上書きされるため、9/19 分は
`wandb_run_id_20260919_143207.txt` へ退避した。同じ内容は
`manifests/<execution_id>.json` にも入っている。

## 関連

- [docs/operation-report-20260919.md](operation-report-20260919.md) — 前日の運用記録
- [docs/production-runbook.md](production-runbook.md) — 当日の実行手順
- [docs/system-count-operation.md](system-count-operation.md) — `system_count` の初期化
- [docs/decisions/0003-camera-input-and-recording.md](decisions/0003-camera-input-and-recording.md) — カメラ入力と録画の設計

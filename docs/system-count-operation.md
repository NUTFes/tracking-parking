# system_count の運用手順

稼働開始時に `system_count` を実際の駐車台数へ合わせる手順。**この工程を飛ばすと
カウントが静かにずれ続け、デバイス側では二度と直せない。**

2026-09-18 に Jetson 実機で本番APIへ向けた通し実行（2時間49分・イベント104件）を
行い、そこで踏んだ事象と受信側のコードを確認して書いた。

## なぜ必要か

受信側は入庫/出庫の**差分**しか受け取らない。デバイスは絶対値を送らないため、
初期値が実態とずれていると、そのずれは永久に残る。

さらに `system_count` は**0で下限クランプされる**
（[event_usecase.py](https://github.com/NUTFes/tracking-parking-api/blob/main/app/usecases/event_usecase.py)、
`max(0, lot.system_count - 1)`）。初期値が実際の駐車台数より小さいと、出庫イベントが
0に吸われて**消える**。あとから入庫が来ても、消えた分は戻らない。

2026-09-18 の実行がその例。開始時 `system_count=2` に対し実際は多数が駐車済みで、
出庫87件・入庫17件を送った結果、最終値は 0 に張り付いた。差分どおりなら -70 だが、
クランプにより途中の出庫が捨てられている。

### 手入力との自動同期は存在しない

`current_count`（手入力）に合わせて `system_count` が追従する処理は、受信側の
コードに**無い**。両者は意図的に分離されている
（[parking_lot_usecase.py](https://github.com/NUTFes/tracking-parking-api/blob/main/app/usecases/parking_lot_usecase.py)）。

| 操作 | `current_count` | `system_count` |
|---|---|---|
| manager の手入力増減（`adjust_count`） | 更新（0で下限クランプ） | 触らない |
| admin リセット `target: "current"` | 指定値を代入 | 触らない |
| admin リセット `target: "system"` | 触らない | 指定値を代入 |
| デバイスのイベント送信 | 触らない | ±1（出庫は0でクランプ） |

`event_usecase.py` のコメントが設計意図を明記している。

> Deliberately does NOT touch current_count — that field is reserved for manual counts
> (manager adjust / admin reset).

センサーの検知漏れ・誤検知があるため、片方がもう片方を無条件に上書きしないように
してある。**したがって初期化は人の手順として組み込むしかない。**

なお公開ビューア（`app-trapa.nutfes.net`）が表示するのは `current_count` だけで、
`system_count` はフロントエンドの型定義にも存在しない
（[tracking-parking-web `src/api/types.ts`](https://github.com/NUTFes/tracking-parking-web/blob/main/src/api/types.ts)）。
`system_count` をどう直しても公開表示は動かない。逆に手入力は即座に公開画面へ出る
（5秒ごとに自動更新）。

## 前提

- <https://admin-trapa.nutfes.net> に Google サインインできること。許可リスト方式で、
  未登録アカウントは認証自体は通るが `/auth` が 401 を返す
- 対象駐車場の **実際の駐車台数を数えてあること**

## 手順

### A. 初日の朝・駐車台数0から始める場合

全駐車場を一括で0にする。

```
POST /api/v1/parking-lots/reset-all
Body: { "target": "system", "note": "<開催日など>" }
```

**値は指定できず0固定。** 受信側でも「event startup initialization」用と位置づけられて
いる。台数0から始められるときだけ使う。

### B. 途中から稼働を開始する場合（および、ずれに気づいたとき）

対象駐車場だけ、実測台数を指定する。

```
POST /api/v1/parking-lots/{lot_id}/reset
Body: { "count": <実測台数>, "target": "system", "note": "<理由>" }
```

`count` は**任意の値を指定できる**（0固定ではない）。`target` の指定を誤って
`"current"` にすると公開ビューアの表示が書き換わるので注意する。

両エンドポイントとも admin 認証が必須で、変更は `parking_activities` に
`actor_label` 付きで監査記録される。

## 確認

読み取りは認証不要なので、Jetson からそのまま確認できる。

```bash
curl -s https://api-trapa.nutfes.net/api/v1/parking-lots | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d if isinstance(d, list) else d.get('items', d.get('data', []))
print(f\"{'id':>3} {'name':<22} {'capacity':>9} {'current':>8} {'system':>7} {'device':>7}\")
for r in rows:
    print(f\"{r.get('id',''):>3} {str(r.get('name','')):<22} {str(r.get('capacity','')):>9} \"
          f\"{str(r.get('current_count','')):>8} {str(r.get('system_count','')):>7} \"
          f\"{str(r.get('has_device','')):>7}\")
"
```

リセットの前後で実行し、`system_count` が意図した値になったこと、`current_count` が
**変わっていない**ことを両方確認する。

2026-09-18 時点で `has_device=true` は2件。Jetson（`jetson-production.env` の
`DEVICE_API_KEY`）が紐づくのは **`講義棟北` (id=3, capacity 200)**。

```
 id name                    capacity  current  system  device
  3 講義棟北                      200       83       0    True
  6 RIセンター北                    5        5      10    True
```

## 運用チェックリスト

| タイミング | 操作 |
|---|---|
| 稼働開始前 | 実際の駐車台数を数える |
| 稼働開始前 | A または B で `system_count` を合わせる |
| 稼働開始前 | 上の `curl` で反映を確認 |
| 稼働中 | `data/outputs/unsent_events.jsonl` が溜まっていないか見る（溜まっていれば送信先に到達できていない） |
| 稼働終了 | **SIGINT で停止する。** `kill -9` は書きかけの録画セグメントが再生不能になる |

停止は `run_production.sh` の案内どおり Ctrl+C（SIGINT）でよい。フレーム境界で抜けて
イベントログ・CSV・マニフェストを保存してから終了する。

## 注意点

- **ずれはデバイス側では直せない。** 再起動しても `system_count` は受信側が持つ値の
  ままで、Jetson は差分を送り続けるだけ。直すには必ず admin のリセットが要る
- **`reset-all` は全駐車場が対象。** 1箇所だけ直したいときに使わない
- 送信先に到達できない間のイベントは `data/outputs/unsent_events.jsonl` へ退避され、
  次回起動時に再送される。再送は `request_id` によるべき等性で保護されているので
  二重計上にはならない（受信側が重複 `request_id` を検出して既存イベントを返す）。
  ただし**再送されたイベントもクランプの対象**なので、長時間の断線後は初期値の
  ずれが表面化しやすい

## 関連

- [docs/api-verification.md](api-verification.md) — API送信機能そのものの検証手順
- [docs/decisions/0002-api-event-delivery.md](decisions/0002-api-event-delivery.md) — 送信方式の決定記録
- [tracking-parking-api](https://github.com/NUTFes/tracking-parking-api) — 受信側の実装
- [tracking-parking-admin-web](https://github.com/NUTFes/tracking-parking-admin-web) — admin画面の実装

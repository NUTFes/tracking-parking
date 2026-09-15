"""
送信失敗の分類と再送可否の判定

POST /events は request_id（べき等キー）を伴って送るため、「届いたか不明」な
失敗も安全に再送できる。ここでの分類（RETRY/UNKNOWN/DROP）は再送の可否には
使わず（is_retryable が RETRY/UNKNOWN をどちらもTrueにする）、診断のために
残す。「送られていないと確定」と「届いたか不明」は原因調査上まったく別の
情報だからである。

requestsとurllib3は各関数の内部で遅延importする。api/ 配下のモジュールを
import しただけではrequestsが読み込まれないようにするため（client.pyの
遅延import方針、common/wandb_logger.pyのExperimentLoggerと同じ考え方）。
"""

from enum import StrEnum


class Disposition(StrEnum):
    OK = "ok"
    RETRY = "retry"  # リクエストが送られていないと確定 → 再送してよい
    UNKNOWN = "unknown"  # 届いたか不明。request_idがあるので再送してよい
    DROP = "drop"  # 設定の誤り → 再送しない


def _inner_exception(exc: BaseException) -> BaseException | None:
    """requests の ConnectionError が包んでいる urllib3 例外を1段だけ取り出す。

    接続拒否・名前解決失敗では exc.args[0] が MaxRetryError で、.reason に
    NewConnectionError / NameResolutionError が入る（実測で確認済み）。
    送信後に切れた場合は exc.args[0] が ProtocolError そのもの
    （requests の HTTPAdapter.send が raise ConnectionError(err) する実装のため）。
    """
    from urllib3.exceptions import MaxRetryError

    args = getattr(exc, "args", ())
    arg = args[0] if args else None
    if isinstance(arg, MaxRetryError):
        return arg.reason
    return arg if isinstance(arg, BaseException) else None


def classify_exception(exc: BaseException) -> Disposition:
    """送信時の例外を分類する。

    判定順が重要: requests.exceptions.ConnectTimeout は ConnectionError と
    Timeout の両方を継承しているため、素の ConnectionError より先に判定
    しないと誤って「送信後に切れた」側へ落ちる。

    素の ConnectionError を一律 RETRY にしないこと。送信後に切れた
    ProtocolError 由来の ConnectionError まで再送すると、request_id が
    無かった頃のM1設計では二重計上の直接原因だった。request_idがある今は
    実害はないが、分類の正確さ自体に診断上の価値があるため維持する。
    """
    import requests.exceptions as rexc
    from urllib3.exceptions import NewConnectionError

    if isinstance(exc, rexc.ConnectTimeout):
        return Disposition.RETRY

    if isinstance(exc, rexc.ConnectionError):
        inner = _inner_exception(exc)
        if isinstance(inner, NewConnectionError):
            # 接続拒否・名前解決失敗（NameResolutionErrorはこの派生）。
            return Disposition.RETRY
        # ProtocolError由来の切断、SSLError、ProxyErrorなど。
        # 送信後に切れた可能性があるため「届いたか不明」。
        return Disposition.UNKNOWN

    if isinstance(exc, (rexc.ReadTimeout, rexc.Timeout)):
        return Disposition.UNKNOWN

    if isinstance(exc, (rexc.ChunkedEncodingError, rexc.ContentDecodingError)):
        # 応答の受信途中。サーバー側の処理自体は完了している。
        return Disposition.UNKNOWN

    if isinstance(
        exc,
        (rexc.MissingSchema, rexc.InvalidSchema, rexc.InvalidURL, rexc.URLRequired, rexc.TooManyRedirects),
    ):
        # API_BASE_URLの書き間違いなど、再送しても直らない設定の誤り。
        return Disposition.DROP

    # 未知の例外は保守側（UNKNOWN）に倒す。誤分類の代償は「余分な再送」で
    # あって「イベントの欠落」ではない。request_idがあるので再送は安全。
    return Disposition.UNKNOWN


def classify_status(status_code: int) -> Disposition:
    """HTTPステータスコードを分類する。

    POSTはallow_redirects=Falseで投げるため3xxは想定外（設定の誤り扱い）。
    408（Request Timeout）と429（Too Many Requests）は、APIキーやURL・
    ペイロードの誤りとは性質が異なる一時的な失敗のため、他の4xxとは分けて
    UNKNOWN（再送可能）に含める。それ以外の4xxは再送しても直らない設定の
    誤りとして扱う。5xxはサーバーがトランザクションをコミットしてから
    落ちた可能性がある。
    """
    if 200 <= status_code < 300:
        return Disposition.OK
    if 500 <= status_code < 600:
        return Disposition.UNKNOWN
    if status_code in (408, 429):
        return Disposition.UNKNOWN
    return Disposition.DROP


def is_retryable(disposition: Disposition) -> bool:
    """この disposition のイベントを再送してよいか。

    RETRYとUNKNOWNのどちらもTrueを返す。UNKNOWNを再送してよいのは、
    POST /events に request_id（べき等キー）を含めて送っているからである。
    サーバーは同じrequest_idの2回目を2xxで受理しつつ既存イベントを返し、
    system_countを動かさない契約になっている。request_idを送るのをやめる
    変更が入ったら、この関数もUNKNOWNをFalseへ戻さないと二重計上が復活する。

    ack（POST /commands/{id}/ack）とハートビート（POST /heartbeat）には
    この関数を適用しない。台数への副作用が無いため、常に再送してよい。
    """
    return disposition in (Disposition.RETRY, Disposition.UNKNOWN)

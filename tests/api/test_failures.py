"""送信失敗の分類（failures.py）に関するテスト。

request_id（べき等キー）を送っている前提でUNKNOWNも再送してよいことに
しているため、分類そのものを間違えると診断ログの意味が壊れる。特に
ConnectTimeoutがConnectionErrorとTimeoutの両方の派生であることと、
「送信後に切れたConnectionError」を誤ってRETRYにしないことは、この
モジュールの存在理由そのものなので重点的に確認する。
"""
import requests
from urllib3.exceptions import MaxRetryError, NameResolutionError, NewConnectionError, ProtocolError

from tracking_parking.api.failures import Disposition, classify_exception, classify_status, is_retryable


def test_ConnectTimeoutはRETRY():
    assert classify_exception(requests.exceptions.ConnectTimeout("timed out")) == Disposition.RETRY


def test_ConnectTimeoutは両親を持つが先に判定されるためRETRYのまま():
    """ConnectTimeoutはConnectionErrorとTimeoutの両方の派生。

    isinstance(exc, ConnectionError)を先に判定してしまうと、内側の例外が
    無い（args[0]がNoneまたは文字列）ためUNKNOWNに落ちてしまう。判定順が
    入れ替わっていないことをMROの事実で固定する。
    """
    exc = requests.exceptions.ConnectTimeout("timed out")
    assert isinstance(exc, requests.exceptions.ConnectionError)
    assert isinstance(exc, requests.exceptions.Timeout)
    assert classify_exception(exc) == Disposition.RETRY


def test_接続拒否はRETRY():
    inner = NewConnectionError(None, "Connection refused")
    mre = MaxRetryError(pool=None, url="http://x", reason=inner)
    exc = requests.exceptions.ConnectionError(mre)
    assert classify_exception(exc) == Disposition.RETRY


def test_名前解決失敗はRETRY():
    """NameResolutionErrorはNewConnectionErrorの派生なので同じ分岐で拾える。"""
    inner = NameResolutionError(None, "host", "Name or service not known")
    assert isinstance(inner, NewConnectionError)
    mre = MaxRetryError(pool=None, url="http://x", reason=inner)
    exc = requests.exceptions.ConnectionError(mre)
    assert classify_exception(exc) == Disposition.RETRY


def test_送信後に切れたConnectionErrorはUNKNOWN():
    """二重計上を防ぐ要のテスト。ConnectionErrorだからといって一律RETRYにしない。"""
    pe = ProtocolError("Connection aborted.", ConnectionResetError())
    exc = requests.exceptions.ConnectionError(pe)
    assert classify_exception(exc) == Disposition.UNKNOWN


def test_SSLErrorはConnectionErrorの派生だがUNKNOWN():
    exc = requests.exceptions.SSLError("cert verify failed")
    assert isinstance(exc, requests.exceptions.ConnectionError)
    assert classify_exception(exc) == Disposition.UNKNOWN


def test_ProxyErrorはConnectionErrorの派生だがUNKNOWN():
    exc = requests.exceptions.ProxyError("proxy failed")
    assert isinstance(exc, requests.exceptions.ConnectionError)
    assert classify_exception(exc) == Disposition.UNKNOWN


def test_ReadTimeoutはUNKNOWN():
    assert classify_exception(requests.exceptions.ReadTimeout("read timed out")) == Disposition.UNKNOWN


def test_ChunkedEncodingErrorはUNKNOWN():
    assert classify_exception(requests.exceptions.ChunkedEncodingError("bad chunk")) == Disposition.UNKNOWN


def test_URLの書き間違いはDROP():
    assert classify_exception(requests.exceptions.MissingSchema("invalid url")) == Disposition.DROP
    assert classify_exception(requests.exceptions.InvalidURL("bad url")) == Disposition.DROP


def test_未知の例外はUNKNOWNへ倒す():
    """既定を保守側にする。誤分類の代償はイベントの欠落ではなく余分な再送で済む。"""
    assert classify_exception(ValueError("何か別のエラー")) == Disposition.UNKNOWN


def test_2xxはOK():
    assert classify_status(200) == Disposition.OK
    assert classify_status(201) == Disposition.OK


def test_4xxはDROP():
    for code in (400, 401, 403, 404, 422):
        assert classify_status(code) == Disposition.DROP


def test_408と429は一時的な失敗としてUNKNOWNに分類する():
    """設定の誤りではなく一時的な失敗のため、他の4xxとは異なりDROPにしない。
    DROPはスプールに残らず再送されないため、混雑時に恒久的な欠落になる。"""
    assert classify_status(408) == Disposition.UNKNOWN
    assert classify_status(429) == Disposition.UNKNOWN


def test_3xxはDROP():
    assert classify_status(301) == Disposition.DROP


def test_5xxはUNKNOWN():
    for code in (500, 502, 503):
        assert classify_status(code) == Disposition.UNKNOWN


def test_is_retryableはRETRYとUNKNOWNをどちらもTrueにする():
    assert is_retryable(Disposition.RETRY) is True
    assert is_retryable(Disposition.UNKNOWN) is True
    assert is_retryable(Disposition.DROP) is False
    assert is_retryable(Disposition.OK) is False


def test_is_retryableのdocstringにrequest_idへの依存が明記されている():
    """将来request_idを送るのをやめる変更が入ったとき、ここを読んで危険に気づけるように。"""
    assert "request_id" in is_retryable.__doc__


def test_disposition_str_is_plain_value():
    """str(Disposition.X) が値そのものになること。

    sender.py が str(disposition) の結果をスプールのJSONLへ書くため、
    ここが 'Disposition.RETRY' のような表現に変わるとスプールが静かに壊れる。
    Python 3.10 では StrEnum が無く互換実装に落ちるので、その挙動を固定する。
    """
    assert str(Disposition.OK) == "ok"
    assert str(Disposition.RETRY) == "retry"
    assert str(Disposition.UNKNOWN) == "unknown"
    assert str(Disposition.DROP) == "drop"
    assert f"{Disposition.RETRY}" == "retry"

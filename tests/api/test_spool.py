"""未送信イベントのスプール（spool.py）に関するテスト。

request_idがあるので届いたかどうかを気にせず全件再送してよい、という
設計の前提そのものを、request_idが読み書きの往復で保たれることで確認する。
壊れた行・未知バージョンの行は再送せず、そのまま残すことも確認する
（形式変更時に古い行を誤って送信しないための安全弁）。
"""
from tracking_parking.api.spool import append_record, load, new_record, rewrite


def make_record(request_id="r1", **overrides):
    base = dict(
        spooled_at="2026-09-15T10:00:00+09:00",
        request_id=request_id,
        event_type="entry",
        detected_at="2026-09-15T09:59:58+09:00",
        vehicle_track_id="7",
        disposition="unknown",
        error="boom",
        execution_id="exec-1",
    )
    base.update(overrides)
    return new_record(**base)


def test_書いて読み直すと同じ内容が戻る(tmp_path):
    path = tmp_path / "spool.jsonl"
    record = make_record()
    append_record(path, record)
    contents = load(path)
    assert len(contents.records) == 1
    assert contents.records[0] == record


def test_request_idが往復する(tmp_path):
    """べき等の前提そのもの。再送時に同じrequest_idが送られることを保証する。"""
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record(request_id="dup-123"))
    contents = load(path)
    assert contents.records[0].request_id == "dup-123"


def test_appendはtruncateしない(tmp_path):
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record(request_id="r1"))
    append_record(path, make_record(request_id="r2"))
    contents = load(path)
    assert [r.request_id for r in contents.records] == ["r1", "r2"]


def test_存在しないファイルを読むと空になる(tmp_path):
    contents = load(tmp_path / "nope.jsonl")
    assert contents.records == []
    assert contents.passthrough_lines == []


def test_壊れたJSON行は残るが再送対象にならない(tmp_path):
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record(request_id="ok"))
    with path.open("a", encoding="utf-8") as f:
        f.write("this is not json\n")
    contents = load(path)
    assert [r.request_id for r in contents.records] == ["ok"]
    assert contents.passthrough_lines == ["this is not json"]


def test_未知のschema_versionの行は残るが再送対象にならない(tmp_path):
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record(request_id="ok"))
    unknown_line = '{"schema_version": 999, "request_id": "future"}'
    with path.open("a", encoding="utf-8") as f:
        f.write(unknown_line + "\n")
    contents = load(path)
    assert [r.request_id for r in contents.records] == ["ok"]
    assert contents.passthrough_lines == [unknown_line]


def test_with_retry_resultはattemptsを増やしspooled_atを保つ():
    record = make_record()
    updated = record.with_retry_result(disposition="unknown", error="again")
    assert updated.attempts == record.attempts + 1
    assert updated.spooled_at == record.spooled_at
    assert updated.last_error == "again"


def test_rewriteは渡した行だけを残す(tmp_path):
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record(request_id="r1"))
    append_record(path, make_record(request_id="r2"))
    contents = load(path)
    remaining = [r for r in contents.records if r.request_id == "r2"]
    rewrite(path, records=remaining, passthrough_lines=[])
    after = load(path)
    assert [r.request_id for r in after.records] == ["r2"]


def test_rewriteは壊れた行も一緒に保持できる(tmp_path):
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record(request_id="r1"))
    with path.open("a", encoding="utf-8") as f:
        f.write("broken\n")
    contents = load(path)
    rewrite(path, records=contents.records, passthrough_lines=contents.passthrough_lines)
    after = load(path)
    assert [r.request_id for r in after.records] == ["r1"]
    assert after.passthrough_lines == ["broken"]


def test_rewriteで全て空になるとファイルが消える(tmp_path):
    path = tmp_path / "spool.jsonl"
    append_record(path, make_record())
    rewrite(path, records=[], passthrough_lines=[])
    assert not path.exists()


def test_全件空でrewriteしてもファイルが無ければ何も起きない(tmp_path):
    path = tmp_path / "does-not-exist.jsonl"
    rewrite(path, records=[], passthrough_lines=[])
    assert not path.exists()


def test_appendは親ディレクトリを作る(tmp_path):
    path = tmp_path / "nested" / "dir" / "spool.jsonl"
    append_record(path, make_record())
    assert path.exists()

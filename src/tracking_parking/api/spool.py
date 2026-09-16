"""
未送信イベントのスプール（JSONL）

スプールに載ったレコードはすべて再送対象になる。POST /events が
request_id（べき等キー）を伴うため、届いていたかどうかを気にせず
全件送り直してよい（届いていればサーバーが2xxで既存イベントを返し、
system_countは動かさない）。

このモジュールはファイルI/Oとレコードの表現だけを扱う。送信の再試行
そのものはsender.pyが行う。client.EventPayloadには依存しない
（役割を保つための意図的な分離）。
"""

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SpoolRecord:
    """スプールのJSONL 1行に対応する。"""

    schema_version: int
    spooled_at: str
    request_id: str
    event_type: str
    detected_at: str
    vehicle_track_id: str | None
    attempts: int
    last_disposition: str | None
    last_error: str | None
    execution_id: str | None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "SpoolRecord":
        return cls(
            schema_version=data["schema_version"],
            spooled_at=data["spooled_at"],
            request_id=data["request_id"],
            event_type=data["event_type"],
            detected_at=data["detected_at"],
            vehicle_track_id=data.get("vehicle_track_id"),
            attempts=data["attempts"],
            last_disposition=data.get("last_disposition"),
            last_error=data.get("last_error"),
            execution_id=data.get("execution_id"),
        )

    def with_retry_result(self, *, disposition: str, error: str | None) -> "SpoolRecord":
        """再送を試みた結果でattempts/last_disposition/last_errorだけ更新した新しいレコードを返す。

        spooled_at（最初にスプールへ落ちた時刻）は変えない。診断のために
        「どれだけ長く滞留しているか」を残すため。
        """
        return replace(self, attempts=self.attempts + 1, last_disposition=disposition, last_error=error)


def new_record(
    *,
    spooled_at: str,
    request_id: str,
    event_type: str,
    detected_at: str,
    vehicle_track_id: str | None,
    disposition: str,
    error: str | None,
    execution_id: str | None,
) -> SpoolRecord:
    """送信に失敗した直後、初めてスプールへ落とす1件を組み立てる。"""
    return SpoolRecord(
        schema_version=SCHEMA_VERSION,
        spooled_at=spooled_at,
        request_id=request_id,
        event_type=event_type,
        detected_at=detected_at,
        vehicle_track_id=vehicle_track_id,
        attempts=1,
        last_disposition=disposition,
        last_error=error,
        execution_id=execution_id,
    )


@dataclass(frozen=True)
class SpoolContents:
    """load()の結果。

    records: schema_versionが現行のスキーマと一致し、正しくパースできた行。再送対象。
    passthrough_lines: 壊れた行・未知のschema_versionの行。読めないので黙って捨てず、
        そのまま残す（再送はしない）。形式変更時に古い行を誤って送信しないための安全弁。
    """

    records: list[SpoolRecord]
    passthrough_lines: list[str]


def load(path: Path) -> SpoolContents:
    """スプールファイルを読む。存在しなければ空の内容を返す。"""
    path = Path(path)
    if not path.exists():
        return SpoolContents(records=[], passthrough_lines=[])

    records: list[SpoolRecord] = []
    passthrough: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            passthrough.append(line)
            continue
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            passthrough.append(line)
            continue
        try:
            records.append(SpoolRecord.from_dict(data))
        except (KeyError, TypeError, ValueError):
            passthrough.append(line)
            continue

    return SpoolContents(records=records, passthrough_lines=passthrough)


def append_record(path: Path, record: SpoolRecord) -> None:
    """1件をスプールの末尾へ追記する（truncateしない）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(record.to_json_line() + "\n")


def rewrite(path: Path, *, records: list[SpoolRecord], passthrough_lines: list[str]) -> None:
    """再送を試みた後の状態でスプール全体を書き直す。

    一時ファイルへ書いてos.replace()する（POSIXで原子的）。残すのは
    引数で渡された「まだ未解決の行」だけで、成功して除かれた行はここへ
    渡さないことで自然に消える。records/passthrough_linesが両方空なら
    ファイル自体を削除する。
    """
    path = Path(path)
    if not records and not passthrough_lines:
        if path.exists():
            path.unlink()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    lines = [record.to_json_line() for record in records] + list(passthrough_lines)
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)

"""ROI設定JSON（data/inputs/configs/*.json）の読み書き。

既存契約（video / roi / in / out / 任意のevents・tolerance_sec）を壊さず、
単一のネストキー `roi_setup` を追加する。GUI（roi_setup/setup_roi.py）が
書き込むのはこの `roi` と `roi_setup` の2キーのみで、`in`/`out`/`events`/
`tolerance_sec`や未知キーには触れない。

I/O（load_roi_config / write_roi_config）と純ロジック（それ以外）を分離
している。純ロジックだけがテスト対象になり、cv2/YOLOをモックしない既存の
テスト規約にそのまま乗る。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_S_LOW = 0.25
DEFAULT_S_HIGH = 0.75

ROI_SETUP_KEY = "roi_setup"
ROI_SETUP_SCHEMA_VERSION = 1

# GUI・progress.py（edge_distance方式）が要求する頂点順序。src/roi.pyの
# VERTEX_ORDERと同一の値を持つ（roi_config.pyはroi.pyに依存させず、
# 値だけを複製する。両者が食い違えばテストが検出する）。
VERTEX_ORDER = ("far_left", "far_right", "near_right", "near_left")


@dataclass(frozen=True)
class RoiConfig:
    """設定JSONから読み出した、GUI・下流スクリプトが使う値。"""

    path: str
    video: str | int
    roi: tuple[tuple[int, int], ...]
    s_low: float
    s_high: float
    roi_setup: dict[str, Any]
    raw: dict[str, Any]


def parse_video_source(value: Any) -> str | int:
    """JSONの`video`値をカメラindex（int）かパス（str）に正規化する。

    bool は int のサブクラスだが動画ソースとしては無効なので拒否する。
    """
    if isinstance(value, bool):
        raise ValueError(f"videoは真偽値を受け付けません: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    raise ValueError(f"videoは文字列（パス）または整数（カメラindex）である必要があります: {value!r}")


def _coerce_vertex(vertex: Any) -> tuple[int, int]:
    if (
        not isinstance(vertex, (list, tuple))
        or len(vertex) != 2
        or isinstance(vertex[0], bool)
        or isinstance(vertex[1], bool)
    ):
        raise ValueError(f"ROI頂点は[x, y]の2要素である必要があります: {vertex!r}")
    x, y = vertex
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError(
            f"ROI頂点は整数座標である必要があります（draw_roiがint前提のため）: {vertex!r}"
        )
    return (x, y)


def _coerce_roi(raw_roi: Any) -> tuple[tuple[int, int], ...]:
    if not isinstance(raw_roi, list) or len(raw_roi) != 4:
        raise ValueError("roiは4頂点の配列である必要があります")
    return tuple(_coerce_vertex(v) for v in raw_roi)


def load_roi_config(path: str | Path) -> RoiConfig:
    """設定JSONを読み込む。

    Raises:
        FileNotFoundError: パスが存在しない。
        ValueError: JSONとして解釈できない、`video`・`roi`が無い/不正。
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSONとして解釈できません: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"設定ファイルのトップレベルはオブジェクトである必要があります: {path}")

    if "video" not in raw:
        raise ValueError(f"'video'キーがありません: {path}")
    if "roi" not in raw:
        raise ValueError(f"'roi'キーがありません: {path}")

    video = parse_video_source(raw["video"])
    roi = _coerce_roi(raw["roi"])
    roi_setup = raw.get(ROI_SETUP_KEY, {})
    if not isinstance(roi_setup, dict):
        raise ValueError(f"'{ROI_SETUP_KEY}'はオブジェクトである必要があります: {path}")

    s_low = raw.get("s_low", DEFAULT_S_LOW)
    s_high = raw.get("s_high", DEFAULT_S_HIGH)

    return RoiConfig(
        path=str(path),
        video=video,
        roi=roi,
        s_low=float(s_low),
        s_high=float(s_high),
        roi_setup=roi_setup,
        raw=raw,
    )


def build_roi_setup_metadata(
    *,
    frame_width: int,
    frame_height: int,
    baseline_roi: tuple[tuple[int, int], ...],
    reference_frame_path: str,
    reference_frame_sha256: str | None,
    source: str | int,
    source_sha256: str | None,
    frame_index: int | None,
    position_sec: float | None,
    set_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """`roi_setup`ブロックを組み立てる（純関数）。

    frame_index・position_secは要求したシーク値ではなく、cap.read()後に
    cap.get()で読み戻した実測値を渡すこと（コーデックによってシークが
    キーフレーム単位に丸められるため、要求値を書くと嘘になる）。
    """
    is_camera = isinstance(source, int)
    timestamp = now or datetime.now().astimezone()
    return {
        "schema_version": ROI_SETUP_SCHEMA_VERSION,
        "vertex_order": list(VERTEX_ORDER),
        "coordinate_space": "pixel",
        "frame_width": frame_width,
        "frame_height": frame_height,
        "baseline_roi": [list(p) for p in baseline_roi],
        "reference_frame": {
            "path": reference_frame_path,
            "sha256": reference_frame_sha256,
            "source": source,
            "source_type": "camera" if is_camera else "file",
            "source_sha256": None if is_camera else source_sha256,
            "frame_index": frame_index,
            "position_sec": position_sec,
        },
        "set_at": timestamp.isoformat(timespec="seconds"),
        "set_by": set_by,
        "tool": "roi_setup/setup_roi.py",
    }


def roi_points_changed(raw: dict[str, Any], roi_points: tuple[tuple[int, int], ...]) -> bool:
    """保存前チェック用: `raw`に保存済みの内容と比べて書き込みが必要かを判定する。

    `roi_setup`メタデータは`set_at`に現在時刻を含むため常に前回と異なる
    ——metadata全体の等値比較では「変更なし」を検出できない。そこで判定は
    (a) roi座標そのものが変わったか、(b) roi_setupがまだ一度も付与されて
    いないか（既存configへの初回アタッチは常に意味のある変更）の2点のみを
    見る。両方Falseなら、GUIは参照フレームの再撮影や書き込みを丸ごと
    省略してよい（`s`キー連打でset_atだけが動き続ける事故を防ぐ）。
    """
    new_roi = [list(p) for p in roi_points]
    return raw.get("roi") != new_roi or ROI_SETUP_KEY not in raw


def update_roi_config(
    raw: dict[str, Any],
    roi_points: tuple[tuple[int, int], ...],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """`raw`の`roi`と`roi_setup`だけを差し替えたJSONを返す（純関数）。

    `raw`自体は変更しない（04_multi_video_mae.load_configsのcfg = dict(raw)
    は浅いコピーなので、この層で深くコピーする）。`in`/`out`/`events`/
    `tolerance_sec`・未知キーはそのまま保持する。

    Returns:
        (更新後のdict, 変更があったか)。判定はroi_points_changedに委譲する
        （metadata自体の等値比較はしない。set_atが常に変わるため意味を
        なさない）。
    """
    updated = copy.deepcopy(raw)
    changed = roi_points_changed(raw, roi_points)

    updated["roi"] = [list(p) for p in roi_points]
    updated[ROI_SETUP_KEY] = metadata
    return updated, changed


def write_roi_config(path: str | Path, data: dict[str, Any]) -> None:
    """設定JSONを決定的に書き出す。

    同一入力からは同一バイト列（したがって同一sha256）になるよう、
    `sort_keys=False`（挿入順を保ち既存ファイルの見た目を壊さない）で書く。
    """
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8")


def resolve_reference_frame_path(
    video: str | int,
    *,
    timestamp: datetime | None = None,
    explicit: str | Path | None = None,
    base_dir: str | Path = "data/inputs/reference_frames",
) -> Path:
    """参照フレームPNGの保存先を決める。

    `explicit`が指定されていればそれを最優先する。未指定時は
    `{stem}_{YYYYmmdd_HHMMSS}.png`と毎回別ファイルにする（履歴が
    層3のロールバック材料になり、sha256_fileのlru_cacheとの衝突も
    構造的に回避できるため）。
    """
    if explicit is not None:
        return Path(explicit)

    ts = timestamp or datetime.now()
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    stem = "camera" if isinstance(video, int) else Path(video).stem
    return Path(base_dir) / f"{stem}_{stamp}.png"

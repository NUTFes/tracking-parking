"""両検出方式で共有するフレーム速度計測契約。"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Mapping, Any


TIMING_SCHEMA_VERSION = 2
DEFAULT_WARMUP_FRAMES = 30

COMPARISON_CONFIG_KEYS = (
    "input_sha256",
    "model_sha256",
    "frame_width",
    "frame_height",
    "source_fps",
    "vehicle_classes",
    "yolo_conf",
    "yolo_iou",
    "yolo_imgsz",
    "tracker_config",
    "yolo_device",
    "device_name",
    "device_accelerator",
    "warmup_frames",
    "save_video",
    "show_display",
    "timing_schema_version",
)


@dataclass
class Elapsed:
    """``elapsed_ms`` をコンテキスト終了後に参照するための入れ物。"""

    elapsed_ms: float = 0.0


@contextmanager
def elapsed_timer(
    synchronize: Callable[[], None] | None = None,
) -> Iterator[Elapsed]:
    """単調時計で処理時間を測る。非同期デバイスは前後で同期する。"""

    if synchronize is not None:
        synchronize()
    started = time.perf_counter()
    elapsed = Elapsed()
    try:
        yield elapsed
    finally:
        if synchronize is not None:
            synchronize()
        elapsed.elapsed_ms = (time.perf_counter() - started) * 1000.0


def validate_warmup_frames(value: int | str) -> int:
    """warm-up フレーム数を検証する。"""

    try:
        frames = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"WARMUP_FRAMES must be a non-negative integer: {value!r}") from exc
    if frames < 0:
        raise ValueError(f"WARMUP_FRAMES must be >= 0: {frames}")
    return frames


def resolve_model_device(model: Any, configured_device: Any = None) -> str:
    """明示設定を優先し、Ultralytics モデルの実デバイスを推定する。"""

    if configured_device is not None:
        return str(configured_device)

    for candidate in (getattr(model, "device", None), getattr(getattr(model, "model", None), "device", None)):
        if candidate is not None:
            return str(candidate)

    inner = getattr(model, "model", None)
    if inner is not None:
        try:
            return str(next(inner.parameters()).device)
        except (AttributeError, StopIteration, TypeError):
            pass
    return "cpu"


def synchronize_device(device: Any) -> None:
    """CUDA/MPS のキュー完了を待つ。CPU は no-op。"""

    normalized = str(device).lower().strip()
    if normalized.isdigit() or normalized.startswith("cuda"):
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
    elif normalized.startswith("mps"):
        import torch

        if hasattr(torch, "mps") and torch.backends.mps.is_available():
            torch.mps.synchronize()


def model_synchronizer(model: Any, configured_device: Any = None) -> Callable[[], None]:
    """モデルの現在デバイスを毎回確認する同期関数を返す。"""

    return lambda: synchronize_device(resolve_model_device(model, configured_device))


@lru_cache(maxsize=32)
def sha256_file(path: str) -> str | None:
    """比較対象ファイルの SHA-256。カメラ等の非ファイル入力は ``None``。"""

    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_comparison_key(config: Mapping[str, Any]) -> str:
    """速度比較条件を正規化し、同一条件を表すキーを生成する。"""

    normalized = {key: config.get(key) for key in COMPARISON_CONFIG_KEYS}
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrameTiming:
    """成功した1フレームのフェーズ別処理時間。"""

    frame_index: int
    read_ms: float
    inference_tracking_ms: float
    counting_logic_ms: float
    output_ms: float
    end_to_end_ms: float
    is_warmup: bool

    @property
    def core_ms(self) -> float:
        return self.inference_tracking_ms + self.counting_logic_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "is_warmup": self.is_warmup,
            "read_ms": self.read_ms,
            "inference_tracking_ms": self.inference_tracking_ms,
            "counting_logic_ms": self.counting_logic_ms,
            "core_ms": self.core_ms,
            "output_ms": self.output_ms,
            "end_to_end_ms": self.end_to_end_ms,
            # timing schema v1 との互換 alias。新規比較では core_ms を使う。
            "frame_ms": self.core_ms,
        }


def measured_timings(records: list[FrameTiming]) -> list[FrameTiming]:
    """warm-up ではない計測レコードだけを返す。"""

    return [record for record in records if not record.is_warmup]


def require_measured_timings(records: list[FrameTiming]) -> list[FrameTiming]:
    """比較可能なフレームが無い run を成功値として扱わない。"""

    measured = measured_timings(records)
    if not measured:
        raise ValueError("No measured frames remain after warm-up")
    return measured

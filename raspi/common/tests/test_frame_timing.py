import hashlib

import pytest

from common.frame_timing import (
    FrameTiming,
    build_comparison_key,
    elapsed_timer,
    measured_timings,
    require_measured_timings,
    validate_warmup_frames,
)


def make_timing(index: int, warmup: bool) -> FrameTiming:
    return FrameTiming(
        frame_index=index,
        read_ms=1.0,
        inference_tracking_ms=10.0,
        counting_logic_ms=2.0,
        output_ms=3.0,
        end_to_end_ms=17.0,
        is_warmup=warmup,
    )


def test_frame_timing_core_and_legacy_alias():
    row = make_timing(0, False).to_dict()
    assert row["core_ms"] == 12.0
    assert row["frame_ms"] == row["core_ms"]


def test_measured_timings_excludes_warmup():
    records = [make_timing(0, True), make_timing(1, False)]
    assert [record.frame_index for record in measured_timings(records)] == [1]


def test_require_measured_timings_rejects_all_warmup():
    with pytest.raises(ValueError, match="No measured frames"):
        require_measured_timings([make_timing(0, True)])


@pytest.mark.parametrize("value, expected", [(0, 0), ("30", 30)])
def test_validate_warmup_frames(value, expected):
    assert validate_warmup_frames(value) == expected


@pytest.mark.parametrize("value", [-1, "invalid"])
def test_validate_warmup_frames_rejects_invalid(value):
    with pytest.raises(ValueError):
        validate_warmup_frames(value)


def test_comparison_key_is_stable_and_sensitive_to_conditions():
    base = {
        "input_sha256": "input",
        "model_sha256": "model",
        "frame_width": 1920,
        "frame_height": 1080,
        "source_fps": 30.0,
        "vehicle_classes": [2, 7],
        "yolo_conf": 0.25,
        "yolo_iou": 0.7,
        "yolo_imgsz": 640,
        "tracker_config": "botsort.yaml",
        "yolo_device": "cpu",
        "device_name": "raspi5",
        "device_accelerator": "cpu",
        "warmup_frames": 30,
        "save_video": False,
        "show_display": False,
        "timing_schema_version": 2,
    }
    first = build_comparison_key(base)
    assert first == build_comparison_key(dict(reversed(list(base.items()))))
    assert len(first) == hashlib.sha256().digest_size * 2

    changed = dict(base, yolo_imgsz=1280)
    assert build_comparison_key(changed) != first


def test_elapsed_timer_synchronizes_before_and_after(monkeypatch):
    clock = iter([1.0, 1.025])
    monkeypatch.setattr("common.frame_timing.time.perf_counter", lambda: next(clock))
    sync_calls = []

    with elapsed_timer(lambda: sync_calls.append("sync")) as elapsed:
        pass

    assert sync_calls == ["sync", "sync"]
    assert elapsed.elapsed_ms == pytest.approx(25.0)

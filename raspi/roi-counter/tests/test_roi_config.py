import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))              # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))  # roi-counter/scripts/
sys.path.insert(0, str(Path(__file__).parents[2]))              # raspi/（common 共有のため）

mae = importlib.import_module("04_multi_video_mae")

from common.frame_timing import sha256_file
from common.ground_truth import load_ground_truth

from src.roi_config import (
    DEFAULT_S_HIGH,
    DEFAULT_S_LOW,
    ROI_SETUP_KEY,
    VERTEX_ORDER,
    RoiConfig,
    build_roi_setup_metadata,
    load_roi_config,
    parse_video_source,
    resolve_reference_frame_path,
    roi_points_changed,
    update_roi_config,
    write_roi_config,
)


def write_config(gt_dir, name, data):
    path = gt_dir / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def valid_config(**overrides):
    config = {
        "video": "clip.MOV",
        "roi": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "in": 3,
        "out": 1,
    }
    config.update(overrides)
    return config


def sample_metadata(**overrides):
    metadata = build_roi_setup_metadata(
        frame_width=1920,
        frame_height=1080,
        baseline_roi=((0, 0), (100, 0), (100, 100), (0, 100)),
        reference_frame_path="data/inputs/reference_frames/clip_20260819_103000.png",
        reference_frame_sha256="ref-sha",
        source="clip.MOV",
        source_sha256="src-sha",
        frame_index=150,
        position_sec=5.0,
        set_by="ycn",
        now=datetime(2026, 8, 19, 21, 30, 0),
    )
    metadata.update(overrides)
    return metadata


# ── 読み込み ─────────────────────────────────────────────────────────────


def test_load_roi_config_reads_roi_and_video(tmp_path):
    path = write_config(tmp_path, "clip.json", valid_config())

    cfg = load_roi_config(path)

    assert cfg.video == "clip.MOV"
    assert cfg.roi == ((0, 0), (100, 0), (100, 100), (0, 100))
    assert cfg.path == str(path)


def test_load_roi_config_returns_integer_vertices(tmp_path):
    path = write_config(tmp_path, "clip.json", valid_config())

    cfg = load_roi_config(path)

    for x, y in cfg.roi:
        assert isinstance(x, int)
        assert isinstance(y, int)


def test_load_roi_config_accepts_camera_index_video(tmp_path):
    path = write_config(tmp_path, "camera.json", valid_config(video=0))

    cfg = load_roi_config(path)

    assert cfg.video == 0
    assert isinstance(cfg.video, int)


def test_load_roi_config_uses_default_thresholds_when_absent(tmp_path):
    path = write_config(tmp_path, "clip.json", valid_config())

    cfg = load_roi_config(path)

    assert cfg.s_low == DEFAULT_S_LOW
    assert cfg.s_high == DEFAULT_S_HIGH


def test_load_roi_config_reads_thresholds_when_present(tmp_path):
    path = write_config(tmp_path, "clip.json", valid_config(s_low=0.15, s_high=0.60))

    cfg = load_roi_config(path)

    assert cfg.s_low == 0.15
    assert cfg.s_high == 0.60


def test_load_roi_config_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_roi_config(tmp_path / "does_not_exist.json")


def test_load_roi_config_rejects_missing_roi_key(tmp_path):
    invalid = valid_config()
    del invalid["roi"]
    path = write_config(tmp_path, "clip.json", invalid)

    with pytest.raises(ValueError):
        load_roi_config(path)


def test_load_roi_config_rejects_missing_video_key(tmp_path):
    invalid = valid_config()
    del invalid["video"]
    path = write_config(tmp_path, "clip.json", invalid)

    with pytest.raises(ValueError):
        load_roi_config(path)


def test_load_roi_config_rejects_non_integer_vertices(tmp_path):
    invalid = valid_config(roi=[[0.5, 0], [100, 0], [100, 100], [0, 100]])
    path = write_config(tmp_path, "clip.json", invalid)

    with pytest.raises(ValueError):
        load_roi_config(path)


def test_load_roi_config_keeps_unknown_keys_in_raw(tmp_path):
    path = write_config(tmp_path, "clip.json", valid_config(notes="手打ちメモ"))

    cfg = load_roi_config(path)

    assert cfg.raw["notes"] == "手打ちメモ"


def test_load_roi_config_reads_existing_roi_setup(tmp_path):
    metadata = sample_metadata()
    path = write_config(tmp_path, "clip.json", valid_config(roi_setup=metadata))

    cfg = load_roi_config(path)

    assert cfg.roi_setup == metadata


# ── 書き戻し ─────────────────────────────────────────────────────────────


def test_update_roi_config_replaces_only_roi_and_metadata():
    raw = valid_config()
    metadata = sample_metadata()
    new_roi = ((10, 10), (110, 10), (110, 110), (10, 110))

    updated, _ = update_roi_config(raw, new_roi, metadata)

    assert updated["roi"] == [[10, 10], [110, 10], [110, 110], [10, 110]]
    assert updated[ROI_SETUP_KEY] == metadata


def test_update_roi_config_preserves_ground_truth_keys():
    raw = valid_config(
        events=[{"event_id": "e1", "direction": "IN", "t_sec": 1.0}],
        tolerance_sec=6.0,
    )
    metadata = sample_metadata()

    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)

    assert updated["in"] == 3
    assert updated["out"] == 1
    assert updated["events"] == [{"event_id": "e1", "direction": "IN", "t_sec": 1.0}]
    assert updated["tolerance_sec"] == 6.0


def test_update_roi_config_preserves_unknown_keys():
    raw = valid_config(notes="手打ちメモ")
    metadata = sample_metadata()

    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)

    assert updated["notes"] == "手打ちメモ"


def test_update_roi_config_does_not_mutate_input():
    raw = valid_config()
    raw_copy = json.loads(json.dumps(raw))
    metadata = sample_metadata()

    update_roi_config(raw, ((10, 10), (110, 10), (110, 110), (10, 110)), metadata)

    assert raw == raw_copy


def test_update_roi_config_reports_change_on_first_attach():
    # roi座標は既存と同一でも、roi_setupがまだ無いので変更ありと報告する。
    raw = valid_config()
    metadata = sample_metadata()
    same_roi = ((0, 0), (100, 0), (100, 100), (0, 100))

    _, changed = update_roi_config(raw, same_roi, metadata)

    assert changed is True


def test_update_roi_config_reports_no_change_when_roi_setup_already_present():
    raw = valid_config()
    metadata = sample_metadata()
    same_roi = ((0, 0), (100, 0), (100, 100), (0, 100))
    already_attached, _ = update_roi_config(raw, same_roi, metadata)

    # 2回目: 同じroi座標だが、metadataのset_atは異なるタイムスタンプ。
    different_metadata = sample_metadata(now=datetime(2099, 1, 1))
    _, changed = update_roi_config(already_attached, same_roi, different_metadata)

    assert changed is False


def test_update_roi_config_reports_change_when_roi_differs():
    raw = valid_config()
    metadata = sample_metadata()
    already_attached, _ = update_roi_config(
        raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata
    )

    moved_roi = ((5, 0), (100, 0), (100, 100), (0, 100))
    _, changed = update_roi_config(already_attached, moved_roi, metadata)

    assert changed is True


def test_update_roi_config_records_baseline_roi():
    raw = valid_config()
    metadata = sample_metadata()

    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)

    assert updated[ROI_SETUP_KEY]["baseline_roi"] == [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_update_roi_config_does_not_write_thresholds():
    raw = valid_config()
    metadata = sample_metadata()

    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)

    assert "s_low" not in updated
    assert "s_high" not in updated


# ── roi_points_changed ──────────────────────────────────────────────────


def test_roi_points_changed_true_when_roi_setup_absent():
    raw = valid_config()
    same_roi = ((0, 0), (100, 0), (100, 100), (0, 100))

    assert roi_points_changed(raw, same_roi) is True


def test_roi_points_changed_false_for_identical_roi_after_attach():
    raw = valid_config()
    metadata = sample_metadata()
    already_attached, _ = update_roi_config(
        raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata
    )

    assert roi_points_changed(already_attached, ((0, 0), (100, 0), (100, 100), (0, 100))) is False


def test_roi_points_changed_true_when_vertex_moved():
    raw = valid_config()
    metadata = sample_metadata()
    already_attached, _ = update_roi_config(
        raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata
    )

    assert roi_points_changed(already_attached, ((1, 0), (100, 0), (100, 100), (0, 100))) is True


# ── メタデータ ───────────────────────────────────────────────────────────


def test_build_roi_setup_metadata_contains_required_keys():
    metadata = sample_metadata()

    assert metadata["schema_version"] == 1
    assert metadata["vertex_order"] == list(VERTEX_ORDER)
    assert metadata["frame_width"] == 1920
    assert metadata["frame_height"] == 1080
    assert metadata["reference_frame"]["path"].endswith(".png")
    assert metadata["reference_frame"]["sha256"] == "ref-sha"
    assert metadata["set_at"] == "2026-08-19T21:30:00"
    assert metadata["set_by"] == "ycn"
    assert metadata["tool"] == "roi_setup/setup_roi.py"


def test_build_roi_setup_metadata_marks_camera_source():
    metadata = build_roi_setup_metadata(
        frame_width=1280,
        frame_height=720,
        baseline_roi=((0, 0), (100, 0), (100, 100), (0, 100)),
        reference_frame_path="data/inputs/reference_frames/camera_20260819_103000.png",
        reference_frame_sha256="ref-sha",
        source=0,
        source_sha256="should-be-ignored",
        frame_index=None,
        position_sec=None,
        set_by="ycn",
        now=datetime(2026, 8, 19, 21, 30, 0),
    )

    assert metadata["reference_frame"]["source_type"] == "camera"
    assert metadata["reference_frame"]["source_sha256"] is None


def test_build_roi_setup_metadata_uses_measured_frame_position():
    # frame_index/position_secは要求シーク値ではなく実測値をそのまま記録する。
    metadata = sample_metadata(**{})
    assert metadata["reference_frame"]["frame_index"] == 150
    assert metadata["reference_frame"]["position_sec"] == 5.0


# ── 書き込み & 既存契約との往復 ────────────────────────────────────────


def test_write_roi_config_output_is_deterministic(tmp_path):
    raw = valid_config()
    metadata = sample_metadata()
    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)
    path = tmp_path / "clip.json"

    write_roi_config(path, updated)
    first = path.read_bytes()
    write_roi_config(path, updated)
    second = path.read_bytes()

    assert first == second


def test_written_config_is_loadable_by_load_configs(tmp_path):
    raw = valid_config()
    metadata = sample_metadata()
    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)
    path = tmp_path / "clip.json"
    write_roi_config(path, updated)

    configs = mae.load_configs(str(tmp_path))

    assert len(configs) == 1
    cfg = configs[0]
    assert cfg["roi"] == [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert cfg["in"] == 3
    assert cfg["out"] == 1
    assert cfg[ROI_SETUP_KEY] == metadata


def test_written_config_is_loadable_by_load_ground_truth(tmp_path):
    raw = valid_config(
        events=[{"event_id": "e1", "direction": "IN", "t_sec": 1.0}],
        tolerance_sec=6.0,
    )
    metadata = sample_metadata()
    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)
    path = tmp_path / "clip.json"
    write_roi_config(path, updated)

    gt = load_ground_truth("clip.MOV", explicit_path=str(path))

    assert gt.gt_in == 3
    assert gt.gt_out == 1
    assert gt.tolerance_sec == 6.0
    assert len(gt.events) == 1


def test_written_config_changes_ground_truth_sha256(tmp_path):
    # roi_setupの追加はJSONファイル全体のバイト列を変えるため、
    # ground_truth_sha256（延いてはcondition_key）が変わる。これは
    # ROI再設定という条件変更に伴う想定内の挙動であり、仕様として固定する。
    path = tmp_path / "clip.json"
    write_config(tmp_path, "clip.json", valid_config())
    sha256_file.cache_clear()
    before = sha256_file(str(path))

    raw = json.loads(path.read_text())
    metadata = sample_metadata()
    updated, _ = update_roi_config(raw, ((0, 0), (100, 0), (100, 100), (0, 100)), metadata)
    write_roi_config(path, updated)
    sha256_file.cache_clear()
    after = sha256_file(str(path))

    assert before != after


# ── 補助関数 ─────────────────────────────────────────────────────────────


def test_parse_video_source_returns_int_for_camera_index():
    assert parse_video_source(0) == 0
    assert isinstance(parse_video_source(0), int)


def test_parse_video_source_returns_str_for_path():
    assert parse_video_source("data/inputs/clip.MOV") == "data/inputs/clip.MOV"


def test_parse_video_source_rejects_bool():
    with pytest.raises(ValueError):
        parse_video_source(True)


def test_resolve_reference_frame_path_uses_video_stem():
    ts = datetime(2026, 8, 19, 21, 30, 11)
    path = resolve_reference_frame_path("data/inputs/IMG_2787.MOV", timestamp=ts)

    assert path == Path("data/inputs/reference_frames/IMG_2787_20260819_213011.png")


def test_resolve_reference_frame_path_uses_camera_label_for_int_source():
    ts = datetime(2026, 8, 19, 21, 30, 11)
    path = resolve_reference_frame_path(0, timestamp=ts)

    assert path == Path("data/inputs/reference_frames/camera_20260819_213011.png")


def test_resolve_reference_frame_path_honours_explicit_override():
    path = resolve_reference_frame_path(
        "data/inputs/IMG_2787.MOV", explicit="custom/dir/ref.png"
    )

    assert path == Path("custom/dir/ref.png")

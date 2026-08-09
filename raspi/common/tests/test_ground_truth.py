import json

import pytest

from common.frame_timing import COMPARISON_CONFIG_KEYS
from common.ground_truth import (
    GroundTruth,
    build_ground_truth_config,
    build_ground_truth_summary,
    compute_count_error,
    load_ground_truth,
)


def write_gt(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_loads_in_and_out_and_ignores_roi_key(tmp_path):
    video = tmp_path / "clip.MOV"
    write_gt(tmp_path, "clip_gt.json", {"video": "clip.MOV", "roi": [[1, 2]], "in": 22, "out": 0})
    gt = load_ground_truth(str(video))
    assert gt.gt_in == 22
    assert gt.gt_out == 0
    assert gt.sha256 is not None


def test_auto_derives_path_from_video_stem(tmp_path):
    video = tmp_path / "clip.MOV"
    write_gt(tmp_path, "clip_gt.json", {"in": 1, "out": 2})
    gt = load_ground_truth(str(video))
    assert gt.gt_in == 1
    assert gt.gt_out == 2


def test_missing_auto_derived_file_returns_absent_and_warns(tmp_path, capsys):
    video = tmp_path / "clip.MOV"
    gt = load_ground_truth(str(video))
    assert gt == GroundTruth.absent()
    assert "[WARN]" in capsys.readouterr().out


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(tmp_path / "missing_gt.json"))


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "bad_gt.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_non_object_json_raises(tmp_path):
    path = write_gt(tmp_path, "bad_gt.json", [1, 2, 3])
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_null_direction_is_unverified(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": 22, "out": None})
    gt = load_ground_truth(str(tmp_path / "clip.MOV"), str(path))
    assert gt.gt_in == 22
    assert gt.gt_out is None


def test_missing_out_key_is_unverified(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": 22})
    gt = load_ground_truth(str(tmp_path / "clip.MOV"), str(path))
    assert gt.gt_out is None


def test_without_in_and_out_raises(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"roi": []})
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_negative_count_is_rejected(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": -1, "out": 0})
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_boolean_count_is_rejected(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": True, "out": 0})
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_non_numeric_string_is_rejected(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": "abc", "out": 0})
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_numeric_string_is_accepted(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": "22", "out": "0"})
    gt = load_ground_truth(str(tmp_path / "clip.MOV"), str(path))
    assert gt.gt_in == 22
    assert gt.gt_out == 0


def test_non_integral_float_is_rejected(tmp_path):
    path = write_gt(tmp_path, "gt.json", {"in": 22.5, "out": 0})
    with pytest.raises(ValueError):
        load_ground_truth(str(tmp_path / "clip.MOV"), str(path))


def test_camera_source_has_no_ground_truth():
    gt = load_ground_truth(0)
    assert gt == GroundTruth.absent()


def test_video_stem_mismatch_warns_but_loads(tmp_path, capsys):
    path = write_gt(tmp_path, "gt.json", {"video": "other.MOV", "in": 1, "out": 0})
    gt = load_ground_truth(str(tmp_path / "clip.MOV"), str(path))
    assert gt.gt_in == 1
    assert "[WARN]" in capsys.readouterr().out


def test_count_error_sums_both_directions():
    gt = GroundTruth(path=None, sha256=None, gt_in=22, gt_out=0)
    result = compute_count_error(20, 1, gt)
    assert result == {"count_error": 3, "count_error_in": 2, "count_error_out": 1}


def test_count_error_excludes_null_direction():
    gt = GroundTruth(path=None, sha256=None, gt_in=22, gt_out=None)
    result = compute_count_error(20, 5, gt)
    assert result["count_error"] == result["count_error_in"] == 2
    assert result["count_error_out"] is None


def test_count_error_is_none_without_ground_truth():
    result = compute_count_error(20, 5, GroundTruth.absent())
    assert result == {"count_error": None, "count_error_in": None, "count_error_out": None}


def test_count_error_matches_roi_04_formula_when_both_directions_present():
    gt = GroundTruth(path=None, sha256=None, gt_in=22, gt_out=0)
    count_in, count_out = 19, 2
    result = compute_count_error(count_in, count_out, gt)
    assert result["count_error"] == abs(count_in - gt.gt_in) + abs(count_out - gt.gt_out)


def test_comparison_key_ignores_ground_truth_keys():
    for key in ("ground_truth_config", "ground_truth_sha256", "gt_in", "gt_out"):
        assert key not in COMPARISON_CONFIG_KEYS


def test_build_ground_truth_config_keys():
    gt = GroundTruth(path="/tmp/gt.json", sha256="abc", gt_in=22, gt_out=0)
    assert build_ground_truth_config(gt) == {
        "ground_truth_config": "/tmp/gt.json",
        "ground_truth_sha256": "abc",
        "gt_in": 22,
        "gt_out": 0,
    }


def test_build_ground_truth_summary_includes_count_error():
    gt = GroundTruth(path=None, sha256=None, gt_in=22, gt_out=0)
    summary = build_ground_truth_summary(20, 1, gt)
    assert summary["gt_in"] == 22
    assert summary["count_error"] == 3

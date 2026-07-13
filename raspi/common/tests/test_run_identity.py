import json
from pathlib import Path

import pytest

from common.run_identity import (
    build_condition_key,
    build_run_identity,
    canonical_condition_json,
    write_run_manifest,
)


BASE_CONDITION = {
    "logic_name": "roi_counter",
    "input_sha256": "video-a",
    "model_sha256": "model-a",
    "roi_points": [[0, 0], [10, 0], [10, 10], [0, 10]],
    "s_low": 0.25,
    "s_high": 0.75,
}


def test_condition_key_is_insertion_order_independent():
    first = {"a": 1, "b": {"x": True, "y": [1, 2]}}
    second = {"b": {"y": [1, 2], "x": True}, "a": 1}
    assert build_condition_key(first) == build_condition_key(second)


def test_condition_key_preserves_json_value_types():
    assert build_condition_key({"value": 1}) != build_condition_key({"value": "1"})
    assert build_condition_key({"value": 1}) != build_condition_key({"value": 1.0})
    assert build_condition_key({"value": True}) != build_condition_key({"value": 1})


def test_condition_key_rejects_non_finite_float():
    with pytest.raises(ValueError):
        canonical_condition_json({"value": float("nan")})


def test_condition_key_rejects_non_string_nested_keys():
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_condition_json({"nested": {1: "value"}})


@pytest.mark.parametrize(
    ("field", "different_value"),
    [
        ("input_sha256", "video-b"),
        ("model_sha256", "model-b"),
        ("roi_points", [[1, 0], [10, 0], [10, 10], [0, 10]]),
    ],
)
def test_video_model_and_roi_changes_produce_different_condition_keys(
    field, different_value
):
    changed = {**BASE_CONDITION, field: different_value}
    assert build_condition_key(BASE_CONDITION) != build_condition_key(changed)


def test_same_condition_has_same_key_but_different_execution_ids():
    first = build_run_identity(BASE_CONDITION, display_name="run")
    second = build_run_identity(BASE_CONDITION, display_name="run")
    assert first["condition_key"] == second["condition_key"]
    assert first["execution_id"] != second["execution_id"]


def test_write_run_manifest_records_identity_and_outputs(tmp_path: Path):
    identity = build_run_identity(
        BASE_CONDITION,
        display_name="roi_counter__video-a__s_low=0.25",
        execution_id="execution-1",
    )
    config = {**BASE_CONDITION, **identity, "exp_key": identity["condition_key"]}

    manifest_path = tmp_path / "manifests" / "execution-1.json"
    manifest = write_run_manifest(
        manifest_path,
        config=config,
        output_dir=tmp_path,
        output_paths=["result.json", tmp_path / "frames.csv"],
        wandb_run_id="wandb-1",
    )

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved == manifest
    assert saved["condition_key"] == identity["condition_key"]
    assert saved["execution_id"] == "execution-1"
    assert saved["wandb_run_id"] == "wandb-1"
    assert saved["output_dir"] == str(tmp_path.resolve())
    assert saved["output_paths"] == [
        str((tmp_path / "result.json").resolve()),
        str((tmp_path / "frames.csv").resolve()),
    ]


def test_write_run_manifest_requires_identity(tmp_path: Path):
    with pytest.raises(ValueError, match="condition_key"):
        write_run_manifest(
            tmp_path / "manifest.json",
            config={},
            output_dir=tmp_path,
            output_paths=[],
            wandb_run_id=None,
        )

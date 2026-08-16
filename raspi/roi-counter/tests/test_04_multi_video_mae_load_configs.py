import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))          # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))  # roi-counter/scripts/
sys.path.insert(0, str(Path(__file__).parents[2]))           # raspi/（common 共有のため）

mae = importlib.import_module("04_multi_video_mae")

from common.frame_timing import sha256_file
from common.ground_truth import GtEvent


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


def test_load_configs_preserves_existing_config_fields(tmp_path):
    config_path = write_config(tmp_path, "clip.json", valid_config())

    configs = mae.load_configs(str(tmp_path))

    assert len(configs) == 1
    cfg = configs[0]
    assert cfg["video"] == "clip.MOV"
    assert cfg["roi"] == [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert cfg["in"] == 3
    assert cfg["out"] == 1
    assert cfg["_config_path"] == str(config_path)
    assert cfg["_config_sha256"] == sha256_file(str(config_path))


def test_load_configs_stashes_event_ground_truth(tmp_path):
    config_path = write_config(
        tmp_path,
        "clip.json",
        valid_config(
            events=[
                {"event_id": "event-1", "direction": "IN", "t_sec": 12.5},
                {"event_id": "event-2", "direction": "OUT", "t_sec": 40},
            ],
            tolerance_sec=6.0,
        ),
    )

    configs = mae.load_configs(str(tmp_path))

    gt = configs[0]["_gt"]
    assert configs[0]["_config_path"] == str(config_path)
    assert gt.events == (
        GtEvent(event_id="event-1", direction="IN", t_sec=12.5),
        GtEvent(event_id="event-2", direction="OUT", t_sec=40.0),
    )
    assert gt.tolerance_sec == 6.0


@pytest.mark.parametrize("missing_key", ["video", "roi"])
def test_load_configs_skips_missing_video_or_roi(tmp_path, missing_key):
    invalid = valid_config()
    del invalid[missing_key]
    write_config(tmp_path, "invalid.json", invalid)
    write_config(tmp_path, "valid.json", valid_config())

    configs = mae.load_configs(str(tmp_path))

    assert [cfg["video"] for cfg in configs] == ["clip.MOV"]


@pytest.mark.parametrize("missing_key", ["in", "out"])
def test_load_configs_skips_missing_ground_truth_direction(tmp_path, missing_key):
    invalid = valid_config()
    del invalid[missing_key]
    write_config(tmp_path, "invalid.json", invalid)
    write_config(tmp_path, "valid.json", valid_config())

    configs = mae.load_configs(str(tmp_path))

    assert [cfg["video"] for cfg in configs] == ["clip.MOV"]


def test_load_configs_exits_when_all_configs_are_invalid(tmp_path):
    invalid = valid_config()
    del invalid["roi"]
    write_config(tmp_path, "invalid.json", invalid)

    with pytest.raises(SystemExit) as exc_info:
        mae.load_configs(str(tmp_path))

    assert exc_info.value.code == 1

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))  # raspi/

from eval.update_accuracy_from_sam3 import AmbiguousRunError, find_run


class FakeApi:
    def __init__(self, runs=None):
        self.found_runs = runs or []
        self.run_paths = []
        self.filters = []

    def run(self, path):
        self.run_paths.append(path)
        return SimpleNamespace(id=path.rsplit("/", 1)[-1], name="direct")

    def runs(self, project, filters):
        self.filters.append((project, filters))
        return self.found_runs


def test_find_run_prefers_wandb_run_id():
    api = FakeApi()
    run = find_run(
        api,
        {
            "wandb_run_id": "wandb-1",
            "execution_id": "execution-1",
            "condition_key": "condition-1",
        },
    )
    assert run.id == "wandb-1"
    assert api.run_paths == ["tracking-parking/wandb-1"]
    assert api.filters == []


def test_find_run_uses_execution_id_before_condition_key():
    api = FakeApi([SimpleNamespace(id="wandb-1", name="run")])
    run = find_run(
        api,
        {"execution_id": "execution-1", "condition_key": "condition-1"},
    )
    assert run.id == "wandb-1"
    assert api.filters == [
        ("tracking-parking", {"config.execution_id": "execution-1"})
    ]


def test_find_run_stops_on_ambiguous_condition_key():
    api = FakeApi(
        [
            SimpleNamespace(id="wandb-1", name="first"),
            SimpleNamespace(id="wandb-2", name="second"),
        ]
    )
    with pytest.raises(AmbiguousRunError, match="wandb-1.*wandb-2"):
        find_run(api, {"condition_key": "condition-1"})


def test_find_run_supports_legacy_exp_key():
    api = FakeApi([SimpleNamespace(id="wandb-old", name="legacy")])
    run = find_run(api, {"exp_key": "legacy-key"})
    assert run.id == "wandb-old"
    assert api.filters == [
        ("tracking-parking", {"config.exp_key": "legacy-key"})
    ]

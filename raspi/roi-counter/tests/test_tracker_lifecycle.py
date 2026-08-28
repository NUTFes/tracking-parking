import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.tracker_lifecycle import TrackerPreparationError, prepare_model_for_run


class FakeTracker:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1
        if self.fail:
            raise RuntimeError("reset failed")


class FakePredictor:
    def __init__(self, trackers):
        self.trackers = trackers


class FakeModel:
    def __init__(self, trackers=None, with_predictor=True):
        if with_predictor:
            self.predictor = FakePredictor(trackers)


def test_clean_start_when_predictor_does_not_exist():
    model = FakeModel(with_predictor=False)

    result = prepare_model_for_run(model, "model.pt")

    assert result.model is model
    assert result.succeeded is True
    assert result.method == "clean_start"


def test_resets_every_existing_tracker():
    trackers = [FakeTracker(), FakeTracker()]
    model = FakeModel(trackers)

    result = prepare_model_for_run(model, "model.pt")

    assert result.model is model
    assert result.method == "tracker_reset"
    assert [tracker.reset_calls for tracker in trackers] == [1, 1]


def test_reloads_model_when_reset_is_unavailable():
    model = FakeModel([object()])
    replacement = FakeModel(with_predictor=False)
    loaded_paths = []

    def factory(path):
        loaded_paths.append(path)
        return replacement

    result = prepare_model_for_run(model, "model.pt", model_factory=factory)

    assert result.model is replacement
    assert result.method == "model_reload"
    assert loaded_paths == ["model.pt"]


def test_reloads_model_when_tracker_reset_raises():
    tracker = FakeTracker(fail=True)
    model = FakeModel([tracker])
    replacement = FakeModel(with_predictor=False)

    result = prepare_model_for_run(
        model, "model.pt", model_factory=lambda _: replacement
    )

    assert tracker.reset_calls == 1
    assert result.model is replacement
    assert result.method == "model_reload"


def test_raises_when_reset_and_reload_both_fail():
    model = FakeModel([object()])

    def failing_factory(_):
        raise OSError("load failed")

    with pytest.raises(TrackerPreparationError, match="aborting"):
        prepare_model_for_run(model, "model.pt", model_factory=failing_factory)


def test_reloaded_model_is_used_by_the_next_preparation():
    original = FakeModel([object()])
    replacement_tracker = FakeTracker()
    replacement = FakeModel([replacement_tracker])

    first = prepare_model_for_run(
        original, "model.pt", model_factory=lambda _: replacement
    )
    second = prepare_model_for_run(first.model, "model.pt")

    assert first.method == "model_reload"
    assert second.model is replacement
    assert second.method == "tracker_reset"
    assert replacement_tracker.reset_calls == 1

from dataclasses import dataclass
from typing import Any, Callable

import ultralytics
from ultralytics import YOLO


class TrackerPreparationError(RuntimeError):
    """Raised when a clean tracker state cannot be prepared for a run."""


@dataclass(frozen=True)
class TrackerResetResult:
    model: Any
    succeeded: bool
    method: str
    ultralytics_version: str


def prepare_model_for_run(
    model: Any,
    model_path: str,
    model_factory: Callable[[str], Any] = YOLO,
) -> TrackerResetResult:
    """Prepare a model with no tracker state carried over from a previous run.

    Ultralytics keeps predictor trackers when ``persist=True`` is used. Existing
    trackers are reset when the installed version exposes a callable ``reset``
    method. Otherwise a fresh model is loaded so evaluation never continues
    with an unverified tracker state.
    """
    version = ultralytics.__version__
    predictor = getattr(model, "predictor", None)
    trackers = getattr(predictor, "trackers", None) if predictor is not None else None

    if not trackers:
        return TrackerResetResult(model, True, "clean_start", version)

    reset_methods = [getattr(tracker, "reset", None) for tracker in trackers]
    if reset_methods and all(callable(reset) for reset in reset_methods):
        try:
            for reset in reset_methods:
                reset()
            return TrackerResetResult(model, True, "tracker_reset", version)
        except Exception:
            # A partially reset tracker collection is not safe to reuse. Fall
            # through to a complete model reload instead.
            pass

    try:
        reloaded_model = model_factory(model_path)
    except Exception as exc:
        raise TrackerPreparationError(
            "tracker reset and model reload both failed; aborting the evaluation run"
        ) from exc

    return TrackerResetResult(reloaded_model, True, "model_reload", version)

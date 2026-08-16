"""GTと予測イベントの突合、および精度指標の算出。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PredictedEvent:
    """検出方式が出力した1件の予測イベント。"""

    event_id: str
    direction: str  # "IN" or "OUT"
    t_sec: float


@dataclass(frozen=True)
class GtEvent:
    """GTの1物理イベント。raspi.common.ground_truth.GtEvent と同型。"""

    event_id: str
    direction: str
    t_sec: float


@dataclass(frozen=True)
class MatchResult:
    tp: int
    fp: int
    fn: int
    tp_in: int
    fp_in: int
    fn_in: int
    tp_out: int
    fp_out: int
    fn_out: int
    precision: float | None
    recall: float | None
    f1: float | None


def _match_direction(
    predicted: Sequence[PredictedEvent],
    gt: Sequence[GtEvent],
    direction: str,
    tolerance_sec: float,
) -> tuple[int, int, int]:
    predicted_in_direction = [
        (index, event) for index, event in enumerate(predicted) if event.direction == direction
    ]
    gt_in_direction = [
        (index, event) for index, event in enumerate(gt) if event.direction == direction
    ]

    candidates = []
    for predicted_index, predicted_event in predicted_in_direction:
        for gt_index, gt_event in gt_in_direction:
            time_difference = abs(predicted_event.t_sec - gt_event.t_sec)
            if time_difference <= tolerance_sec:
                candidates.append(
                    (
                        time_difference,
                        gt_event.event_id,
                        predicted_event.event_id,
                        predicted_index,
                        gt_index,
                    )
                )

    candidates.sort()
    consumed_predicted: set[int] = set()
    consumed_gt: set[int] = set()
    tp = 0

    for _, _, _, predicted_index, gt_index in candidates:
        if predicted_index in consumed_predicted or gt_index in consumed_gt:
            continue
        consumed_predicted.add(predicted_index)
        consumed_gt.add(gt_index)
        tp += 1

    fp = len(predicted_in_direction) - tp
    fn = len(gt_in_direction) - tp
    return tp, fp, fn


def match_events(
    predicted: Sequence[PredictedEvent],
    gt: Sequence[GtEvent],
    tolerance_sec: float,
) -> MatchResult:
    """予測イベントを方向別にGTへ1対1で突合し、全体の指標を返す。"""

    tp_in, fp_in, fn_in = _match_direction(predicted, gt, "IN", tolerance_sec)
    tp_out, fp_out, fn_out = _match_direction(predicted, gt, "OUT", tolerance_sec)

    tp = tp_in + tp_out
    fp = fp_in + fp_out
    fn = fn_in + fn_out

    precision = tp / (tp + fp) if tp + fp > 0 else None
    recall = tp / (tp + fn) if tp + fn > 0 else None

    if precision is None and recall is None:
        f1 = None
    elif precision is None or recall is None or precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return MatchResult(
        tp=tp,
        fp=fp,
        fn=fn,
        tp_in=tp_in,
        fp_in=fp_in,
        fn_in=fn_in,
        tp_out=tp_out,
        fp_out=fp_out,
        fn_out=fn_out,
        precision=precision,
        recall=recall,
        f1=f1,
    )

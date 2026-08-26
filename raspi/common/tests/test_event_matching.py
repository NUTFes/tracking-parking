from common.event_matching import GtEvent, PredictedEvent, match_events


def test_perfect_match_across_directions():
    predicted = [
        PredictedEvent("pred-in", "IN", 1.0),
        PredictedEvent("pred-out", "OUT", 8.0),
    ]
    gt = [
        GtEvent("gt-in", "IN", 1.0),
        GtEvent("gt-out", "OUT", 8.0),
    ]

    result = match_events(predicted, gt, tolerance_sec=0.5)

    assert result.tp == 2
    assert result.fp == 0
    assert result.fn == 0
    assert result.precision == result.recall == result.f1 == 1.0


def test_tolerance_boundary_is_inclusive():
    predicted = [
        PredictedEvent("at-boundary", "IN", 1.5),
        PredictedEvent("outside", "IN", 3.51),
    ]
    gt = [
        GtEvent("boundary-gt", "IN", 1.0),
        GtEvent("outside-gt", "IN", 3.0),
    ]

    result = match_events(predicted, gt, tolerance_sec=0.5)

    assert result.tp == 1
    assert result.fp == 1
    assert result.fn == 1


def test_direction_mismatch_never_matches():
    result = match_events(
        [PredictedEvent("pred-in", "IN", 4.0)],
        [GtEvent("gt-out", "OUT", 4.0)],
        tolerance_sec=0.0,
    )

    assert result.tp == 0
    assert result.fp_in == 1
    assert result.fn_in == 0
    assert result.tp_out == 0
    assert result.fp_out == 0
    assert result.fn_out == 1


def test_extra_predictions_are_false_positives():
    predicted = [
        PredictedEvent("pred-1", "IN", 1.0),
        PredictedEvent("pred-2", "IN", 2.0),
    ]
    gt = [GtEvent("gt-1", "IN", 1.0)]

    result = match_events(predicted, gt, tolerance_sec=0.1)

    assert result.tp_in == 1
    assert result.fp_in == 1
    assert result.fn_in == 0
    assert result.precision < 1.0
    assert result.recall == 1.0


def test_missing_predictions_are_false_negatives():
    predicted = [PredictedEvent("pred-1", "OUT", 1.0)]
    gt = [
        GtEvent("gt-1", "OUT", 1.0),
        GtEvent("gt-2", "OUT", 2.0),
    ]

    result = match_events(predicted, gt, tolerance_sec=0.1)

    assert result.tp_out == 1
    assert result.fp_out == 0
    assert result.fn_out == 1
    assert result.recall < 1.0


def test_greedy_matching_uses_nearest_time_difference_first():
    predicted = [
        PredictedEvent("pred-near-start", "IN", 0.5),
        PredictedEvent("pred-near-end", "IN", 9.5),
    ]
    gt = [
        GtEvent("gt-start", "IN", 0.0),
        GtEvent("gt-end", "IN", 10.0),
    ]

    result = match_events(predicted, gt, tolerance_sec=20.0)

    assert result.tp == 2
    assert result.fp == 0
    assert result.fn == 0


def test_tie_breaking_is_deterministic_across_input_orderings():
    predicted = [
        PredictedEvent("pred-b", "IN", 1.0),
        PredictedEvent("pred-a", "IN", -1.0),
    ]
    gt = [
        GtEvent("gt-b", "IN", 0.0),
        GtEvent("gt-a", "IN", 0.0),
    ]

    result_in_original_order = match_events(predicted, gt, tolerance_sec=1.0)
    result_in_reversed_order = match_events(
        list(reversed(predicted)), list(reversed(gt)), tolerance_sec=1.0
    )

    assert result_in_original_order == result_in_reversed_order
    assert result_in_original_order.tp == 2


def test_empty_predictions_have_undefined_precision_but_zero_f1():
    result = match_events(
        [],
        [GtEvent("gt-in", "IN", 1.0), GtEvent("gt-out", "OUT", 2.0)],
        tolerance_sec=0.5,
    )

    assert result.tp == 0
    assert result.fp == 0
    assert result.fn == 2
    assert result.precision is None
    assert result.recall == 0.0
    assert result.f1 == 0.0


def test_empty_gt_have_undefined_recall_but_zero_f1():
    result = match_events(
        [PredictedEvent("pred-in", "IN", 1.0), PredictedEvent("pred-out", "OUT", 2.0)],
        [],
        tolerance_sec=0.5,
    )

    assert result.tp == 0
    assert result.fp == 2
    assert result.fn == 0
    assert result.precision == 0.0
    assert result.recall is None
    assert result.f1 == 0.0


def test_both_inputs_empty_leave_all_metrics_undefined():
    result = match_events([], [], tolerance_sec=0.5)

    assert result.tp == result.fp == result.fn == 0
    assert result.precision is None
    assert result.recall is None
    assert result.f1 is None


def test_directions_are_matched_and_counted_independently():
    predicted = [
        PredictedEvent("pred-in", "IN", 1.0),
        PredictedEvent("pred-out", "OUT", 10.0),
    ]
    gt = [
        GtEvent("gt-in", "IN", 1.0),
        GtEvent("gt-out", "OUT", 20.0),
    ]

    result = match_events(predicted, gt, tolerance_sec=0.5)

    assert result.tp_in == 1
    assert result.fp_in == 0
    assert result.fn_in == 0
    assert result.tp_out == 0
    assert result.fp_out == 1
    assert result.fn_out == 1
    assert result.tp == 1
    assert result.fp == 1
    assert result.fn == 1

from pathlib import Path

import pytest

from common.wandb_logger import (
    build_exp_key,
    ExperimentLogger,
    next_log_boundary,
    should_log_frame,
    validate_log_interval_sec,
)


def test_build_exp_key_sorts_keys():
    # キーは昇順ソートされる（辞書の挿入順に依存しない）
    key = build_exp_key(
        "roi_counter", "IMG_2788", "raspi5", {"s_low": 0.25, "s_high": 0.75}
    )
    assert key == "roi_counter__IMG_2788__s_high=0.75_s_low=0.25__raspi5"


def test_build_exp_key_float_format():
    # float は f"{v:g}"（末尾ゼロが落ちる）
    key = build_exp_key("l", "d", "dev", {"a": 0.100, "b": 1.0})
    assert key == "l__d__a=0.1_b=1__dev"


def test_build_exp_key_insertion_order_independent():
    k1 = build_exp_key("l", "d", "dev", {"a": 1, "b": 2})
    k2 = build_exp_key("l", "d", "dev", {"b": 2, "a": 1})
    assert k1 == k2


def test_disabled_logger_is_noop(tmp_path: Path):
    lg = ExperimentLogger(
        project="p",
        config={"exp_key": "k"},
        group="g",
        job_type="speed_eval",
        tags=["t"],
        enabled=False,
    )
    # 全メソッドが例外を出さず no-op（wandb を import しない）
    assert lg.run_id is None
    lg.define_metric("net_flow", step_metric="t_rel_sec")
    lg.log_frame(0, {"x": 1})
    lg.set_summary("a", 1)
    lg.set_summaries({"b": 2})
    lg.update_running_summary({"c": 3})
    lg.init_accuracy_placeholders()
    lg.save_run_id(tmp_path)
    lg.append_to_result_json(tmp_path / "result.json")
    lg.finish(0)

    # 無効時はファイルを書かない
    assert not (tmp_path / "wandb_run_id.txt").exists()


def test_validate_log_interval_sec_accepts_positive():
    assert validate_log_interval_sec("5") == 5.0
    assert validate_log_interval_sec(0.1) == 0.1


def test_validate_log_interval_sec_rejects_zero():
    with pytest.raises(ValueError):
        validate_log_interval_sec(0)


def test_validate_log_interval_sec_rejects_negative():
    with pytest.raises(ValueError):
        validate_log_interval_sec(-5)


def test_validate_log_interval_sec_rejects_nan():
    with pytest.raises(ValueError):
        validate_log_interval_sec(float("nan"))


def test_validate_log_interval_sec_rejects_inf():
    with pytest.raises(ValueError):
        validate_log_interval_sec(float("inf"))
    with pytest.raises(ValueError):
        validate_log_interval_sec(float("-inf"))


def test_validate_log_interval_sec_rejects_bad_string():
    with pytest.raises(ValueError):
        validate_log_interval_sec("abc")


def test_next_log_boundary_advances_one_interval():
    # next_log_sec == t_rel_sec（等号境界）でも1区間進める（旧 `<=` 意味論を維持）
    assert next_log_boundary(0.0, 0.0, 5.0) == 5.0


def test_next_log_boundary_advances_within_interval():
    assert next_log_boundary(0.0, 3.0, 5.0) == 5.0


def test_next_log_boundary_skips_multiple_intervals_no_loop():
    # 複数区間分ジャンプしても O(1) で正しい次境界に到達する
    assert next_log_boundary(0.0, 23.0, 5.0) == 25.0


def test_should_log_frame_true_on_boundary_reached():
    assert should_log_frame(5.0, 5.0, False) is True
    assert should_log_frame(4.9, 5.0, False) is False


def test_should_log_frame_true_on_count_changed_before_boundary():
    assert should_log_frame(2.0, 5.0, True) is True


def test_count_changed_log_does_not_disturb_boundary_math():
    # count_changed 起因の早期ログ後も、次の境界計算は絶対時刻(t_rel_sec)のみに基づく
    # ため、定期サンプリングのスケジュールがずれない。
    next_log_sec = 0.0
    interval = 5.0
    # count_changed によって t_rel_sec=2.0 で早期ログが発生したとする
    next_log_sec = next_log_boundary(next_log_sec, 2.0, interval)
    assert next_log_sec == 5.0

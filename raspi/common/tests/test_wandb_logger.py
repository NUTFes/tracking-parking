from pathlib import Path

from common.wandb_logger import build_exp_key, ExperimentLogger


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
    lg.define_metric("current_parked", step_metric="t_rel_sec")
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

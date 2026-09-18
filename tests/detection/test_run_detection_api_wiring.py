"""API送信機能の組み込みがLINE_CONDITION_KEYSを汚染していないことを確認する。

LINE_CONDITION_KEYSはcondition_keyのハッシュ元。API送信先URLやキーの
ような、検知結果に影響しない周辺設定がここへ混入すると、値が変わる
だけでハッシュが変わり、過去のW&B runと比較できなくなる。安い割に
効く回帰テストなので、api/ 配下の実装追加時にここだけは必ず確認する。
"""
import run_detection


def test_LINE_CONDITION_KEYSにapi関連のキーが混入していない():
    api_like_keys = [
        key for key in run_detection.LINE_CONDITION_KEYS
        if "api" in key.lower() or "device_api_key" in key.lower() or "base_url" in key.lower()
    ]
    assert api_like_keys == []


def test_LINE_CONDITION_KEYSは既知のキー集合と一致する():
    """要素数や内容が変わったら、このテストが最初に気づく（スナップショット）。"""
    assert set(run_detection.LINE_CONDITION_KEYS) == {
        "logic_name", "input_type", "input_sha256", "model_sha256",
        "line1_points", "line2_points", "parking_reference_point",
        "ground_truth_sha256", "gt_in", "gt_out", "vehicle_classes", "method",
        "margin_px", "endpoint_margin_px", "crossing_method", "max_frame_gap_sec",
        "cleanup_threshold_sec", "tracker_reset", "log_interval_sec", "yolo_conf",
        "yolo_iou", "yolo_device", "yolo_imgsz", "tracker_config",
        "tracker_config_sha256", "device_name", "device_accelerator",
        "frame_width", "frame_height", "source_fps", "warmup_frames",
        "save_video", "save_logs", "show_display", "timing_schema_version",
        "git_sha", "git_dirty", "git_dirty_fingerprint", "python_version",
        "library_versions",
    }

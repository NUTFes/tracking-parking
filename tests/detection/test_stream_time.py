"""ストリーム時刻の組み立てに関するテスト。

トラッカーの時間窓はここが返す値だけで決まる。動画では再現性（同じ動画なら
何度走らせても同じ判定）、カメラでは実経過との一致が要る。両立させるために
入力種別で基準を変えているので、その分岐そのものを固定する。
"""
import run_detection

compute = run_detection.compute_stream_time_sec


def test_動画ではframe_idとfpsから決まる():
    """処理が何秒かかっても映像内の経過は変わらないので、再現性が保たれる。"""
    assert compute(is_camera_input=False, frame_id=90, fps=30.0, elapsed_sec=999.0) == 3.0


def test_動画では実経過を無視する():
    """同じフレームなら、実行が速くても遅くても同じ時刻になる。"""
    fast = compute(is_camera_input=False, frame_id=45, fps=30.0, elapsed_sec=0.5)
    slow = compute(is_camera_input=False, frame_id=45, fps=30.0, elapsed_sec=120.0)
    assert fast == slow == 1.5


def test_カメラでは実経過を使う():
    """処理が撮影レートに追いつかないと、frame_id/fpsは実経過より短くなる。"""
    assert compute(is_camera_input=True, frame_id=42, fps=30.0, elapsed_sec=3.0) == 3.0


def test_カメラでは処理落ちしても窓が伸びない():
    """30fps宣言を実測14fpsで処理した状況。frame_id/fpsなら1.4秒にしか
    見えないが、実際には3秒経っている。ここで3.0を返さないと窓が倍に伸びる。"""
    assert compute(is_camera_input=True, frame_id=42, fps=30.0, elapsed_sec=3.0) == 3.0
    assert compute(is_camera_input=False, frame_id=42, fps=30.0, elapsed_sec=3.0) == 1.4


def test_fpsが0でも落ちない():
    """CAP_PROP_FPSが0を返す動画がある。ゼロ除算で止めない。"""
    assert compute(is_camera_input=False, frame_id=10, fps=0.0, elapsed_sec=1.0) == 0.0

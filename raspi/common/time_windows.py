"""フレーム単位の時間窓を、撮影fpsに依存しない秒指定から導出する。

trackのcleanup、候補状態の失効、Line1とLine2の対応付けに使う「窓」は、
本来「何秒見失ったか」「何秒以内に通過したか」で決まる量である。
これをフレーム数のまま設定に持つと、同じ設定値が撮影fpsによって別の長さを
意味してしまう（150フレームは30fpsで5秒、10fpsでは15秒）。

検証に使ってきた動画は30fps、実機のRaspberry Piは10fps前後で動くため、
この差は実運用と検証のあいだへ黙ったまま入り込む。設定を秒で持ち、動画を
開いた時点のfpsからフレーム数へ変換することでこれを防ぐ。

変換後のフレーム数はrun configへ併記し、実際に何フレームで動いたかを後から
確認できるようにする。
"""

import math

__all__ = ["frames_from_seconds"]


def frames_from_seconds(seconds: float, fps: float) -> int:
    """秒で指定した時間窓を、そのfpsにおけるフレーム数へ変換する。

    丸めは四捨五入（0.5は切り上げ）。0秒は0フレームのまま返し、「即座に失効
    させる」という指定を保つ。正の秒数が丸めで0フレームになる場合だけは
    1フレームへ切り上げる（窓を指定したのに無効化される事故を防ぐため）。

    Args:
        seconds: 時間窓の長さ（秒）。0以上の有限値。
        fps: 変換先のフレームレート。正の有限値。

    Returns:
        フレーム数。

    Raises:
        ValueError: secondsが負または非有限、fpsが正の有限値でない場合。
    """
    seconds = float(seconds)
    if math.isnan(seconds) or math.isinf(seconds):
        raise ValueError(f"secondsは有限の数である必要があります: {seconds!r}")
    if seconds < 0:
        raise ValueError(f"secondsは0以上である必要があります: {seconds!r}")

    fps = float(fps)
    if math.isnan(fps) or math.isinf(fps) or fps <= 0:
        raise ValueError(f"fpsは正の有限値である必要があります: {fps!r}")

    if seconds == 0.0:
        return 0
    return max(1, math.floor(seconds * fps + 0.5))

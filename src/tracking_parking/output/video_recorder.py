"""アノテーション動画の書き出し先（CPUエンコードとハードウェアエンコード）。

cv2.VideoWriter(mp4v) はCPUでエンコードするため、1280x720で約11.6ms/フレーム
掛かる。実機(Jetson Orin NX)のNVENCへ回すと約5.3msになり、検知ループのフレーム
予算を6ms分空けられる。

OpenCVのGStreamerサポートは無効（cv2.getBuildInformation()が GStreamer: NO）なので
cv2.VideoWriter からNVENCへは届かない。代わりに gst-launch-1.0 を子プロセスとして
起動し、生BGRフレームをstdinへ流す。OpenCV側の対応は不要になる。

長時間の録画はサイズでファイルを分割する。単一のmp4が無限に育つのを防ぐのが
主目的ではなく、mp4のインデックス(moov atom)が終了時に書かれるため、途中で
プロセスが落ちると**それまでの全録画が再生不能になる**のを防ぐのが要点。
分割しておけば失うのは書きかけの1本だけで済む。

分割の基準を時間ではなくサイズにしているのは、書き出しfpsが公称値のままで
実効fpsと一致しないため（30fps宣言のカメラを実測12fpsで処理する）、時間指定が
実時間とずれるのに対し、バイト数はずれないため。各セグメントの正確な時刻は
フレームへ焼き込んだJSTから読む。

パイプラインの形は実測で選んだ。
  - nvvidconv はBGRを受けられないため色変換が必要。BGRx(4byte/px)を渡して
    ハードウェア側で変換させる案は、パイプへ流すバイト数が増えるぶん遅く
    なった（10.5ms）。CPUのvideoconvertへ渡すほうが速い（5.3ms）。
  - queue を挟まないと下流の詰まりがstdin.write()へそのまま伝わる。
  - 残るスパイク（約125ms）は常に1フレーム目で、パイプライン起動のコスト。
    定常状態のp95は約8ms。
"""

import os
import shutil
import subprocess

import cv2

__all__ = ["open_recorder", "nvenc_available", "ENCODER_CHOICES"]

ENCODER_CHOICES = ("auto", "nvenc", "cv2")

# NVENCのデバイスノード。存在しない機体（Orin Nanoなど）ではハードウェア
# エンコーダ自体が無い。
NVENC_DEVICE = "/dev/v4l2-nvenc"

# 検知ループを止めないための設定。queueが埋まったとき leaky=downstream は
# 古いフレームを捨てる。ディスクが満杯になった場合など、下流が止まったときに
# stdin.write()がブロックするとカウント処理ごと止まる。録画は事後分析用で
# カウントより優先されないため、詰まったら録画を欠かす側を選ぶ。
#
# 実運用の間隔では取りこぼしは起きない。検知ループは1フレーム80ms前後で、
# エンコードは5ms程度あるため。1280x720で80ms間隔なら60枚投入して60枚記録、
# 検証クリップ1000フレームの実行でも1000フレーム記録されることを確認済み
# （間隔ゼロで投入し続けると起動中に埋まって間引かれるが、これは設計どおり）。
#
# 枚数で制御するので、バイト数と時間の上限は明示的に外す。max-size-bytes の
# 既定は10MBで、生BGRだと1280x720で2.7MB/フレーム＝約3.8枚しか入らない。
# 枚数指定が効かないまま、この暗黙の上限で間引かれる（24枚投入して13枚しか
# 記録されない状態になっていた）。
QUEUE_BUFFERS = 10

# 分割時のファイル名。連番なのは、gst-launchのCLIからはセグメントごとの
# 時刻名を付けられないため（format-locationシグナルはPython GIバインディングが
# 必要で、この機体には入っていない）。実行開始時刻は親ディレクトリ名に入れ、
# 正確な時刻はフレームへ焼き込んだJSTから読む。
#
# 保持数を指定した場合（max_segments>0）、この番号は循環する。splitmuxsinkの
# max-filesがリングバッファとして動くためで、実測で確認した（2400フレームを
# max-files=3で流すと index 0..2 の3本だけが残り、mtimeでは segment_00000 が
# 最新だった）。**保持数を有効にすると名前から時系列は読めない。** 順序は
# ファイルのmtimeか、フレームへ焼き込んだJSTから判断すること。
SEGMENT_PATTERN = "segment_%05d.mp4"


def nvenc_available() -> bool:
    """この機体でNVENC経路が使えるか。

    gst-launch-1.0 の存在、デバイスノード、プラグインの3つを確認する。
    プラグインの確認だけ子プロセスを起動するため、起動時に一度だけ呼ぶこと。
    """
    if shutil.which("gst-launch-1.0") is None:
        return False
    if not os.path.exists(NVENC_DEVICE):
        return False
    if shutil.which("gst-inspect-1.0") is None:
        return False
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "nvv4l2h264enc"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


class Cv2Recorder:
    """cv2.VideoWriter(mp4v)によるCPUエンコード。"""

    name = "cv2"

    def __init__(self, path: str, *, width: int, height: int, fps: float):
        self._writer = cv2.VideoWriter(
            path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )

    @property
    def is_opened(self) -> bool:
        return self._writer.isOpened()

    def write(self, frame) -> None:
        self._writer.write(frame)

    def release(self) -> None:
        self._writer.release()


class Cv2SegmentedRecorder:
    """cv2.VideoWriterを、サイズで区切って複数ファイルへ書く。

    NVENC経路のsplitmuxsinkと同じ命名規則に揃えている。エンコーダを切り替えても
    出来上がるディレクトリの中身が変わらないようにするため。

    保持数を指定したときの挙動もsplitmuxsinkに合わせてリングバッファにする
    （実測でそう動くことを確認した）。連番を増やしながら古いファイルを消す方式の
    ほうが名前から時系列が読めて望ましいが、splitmuxsink側をそう動かすには
    format-locationシグナル＝Python GIバインディングが必要で、この機体には
    入っていない。両者を食い違わせるより、本番で使う側へ揃えるほうを採る。
    """

    name = "cv2"

    def __init__(self, pattern: str, *, width: int, height: int, fps: float,
                 segment_bytes: int, max_segments: int = 0):
        self._pattern = pattern
        self._width = width
        self._height = height
        self._fps = fps
        self._segment_bytes = segment_bytes
        self._max_segments = max_segments
        self._index = 0
        self._writer = None
        self._open_next()

    def _open_next(self) -> None:
        # 保持数を指定したら名前を使い回す（古いものは上書きで消える）。
        index = (self._index % self._max_segments
                 if self._max_segments > 0 else self._index)
        path = self._pattern % index
        self._writer = cv2.VideoWriter(
            path, cv2.VideoWriter_fourcc(*"mp4v"), self._fps,
            (self._width, self._height)
        )
        self._current_path = path
        self._index += 1

    @property
    def is_opened(self) -> bool:
        return self._writer is not None and self._writer.isOpened()

    def write(self, frame) -> None:
        self._writer.write(frame)
        # サイズはstat()で見る。VideoWriterはバッファするため閾値の判定は
        # 近似になるが、分割の目的（失う範囲を限る）には十分。
        try:
            size = os.path.getsize(self._current_path)
        except OSError:
            return
        if size >= self._segment_bytes:
            self._writer.release()
            self._open_next()

    def release(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


class NvencRecorder:
    """gst-launch-1.0の子プロセスへ生BGRを流し、NVENCでエンコードする。"""

    name = "nvenc"

    def __init__(self, path: str, *, width: int, height: int, fps: float,
                 segment_bytes: int = 0, max_segments: int = 0):
        self._width = width
        self._height = height
        self._expected_bytes = width * height * 3
        self._proc = subprocess.Popen(
            ["gst-launch-1.0", "-q"] + self._pipeline(
                path, width, height, fps, segment_bytes, max_segments
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    @staticmethod
    def _pipeline(path: str, width: int, height: int, fps: float,
                  segment_bytes: int = 0, max_segments: int = 0) -> list:
        # framerateは分数で渡す必要がある。小数のfpsもそのまま表現できるよう
        # 1000分母で与える（30.0→30000/1000）。
        numerator = int(round(fps * 1000))
        if segment_bytes > 0:
            # splitmuxsinkはセグメントごとにmoov atomを書いて確定させる。
            # 途中でプロセスが落ちても、失うのは書きかけの1本だけになる。
            sink = [
                "splitmuxsink", f"location={path}",
                f"max-size-bytes={segment_bytes}",
                f"max-files={max_segments}",
            ]
        else:
            sink = ["mp4mux", "!", "filesink", f"location={path}"]
        return [
            "fdsrc", "fd=0", "!",
            "rawvideoparse", "use-sink-caps=false",
            f"width={width}", f"height={height}", "format=bgr",
            f"framerate={numerator}/1000", "!",
            "queue", f"max-size-buffers={QUEUE_BUFFERS}",
            "max-size-bytes=0", "max-size-time=0", "leaky=downstream", "!",
            "videoconvert", "!",
            "nvvidconv", "!",
            "nvv4l2h264enc", "!",
            "h264parse", "!",
        ] + sink

    @property
    def is_opened(self) -> bool:
        return self._proc.poll() is None and self._proc.stdin is not None

    def write(self, frame) -> None:
        """1フレーム流す。

        パイプはバイト列の位置でフレームを区切るため、サイズが違うフレームを
        1枚でも混ぜると以降すべてがずれる。黙って壊れるより止める。
        """
        if frame.shape[0] != self._height or frame.shape[1] != self._width:
            raise ValueError(
                f"フレームの大きさが録画設定と違います: "
                f"{frame.shape[1]}x{frame.shape[0]} != {self._width}x{self._height}"
            )
        if not self.is_opened:
            return
        try:
            self._proc.stdin.write(frame.tobytes())
        except BrokenPipeError:
            # gst-launchが落ちた。検知は続けたいので例外にはせず、理由を出す。
            print(f"[WARN] 録画プロセスが終了しました: {self._stderr_tail()}")

    def release(self) -> None:
        """stdinを閉じてプロセスの終了を待つ。

        待つ必要があるのは、mp4のインデックス(moov atom)が終了時に書かれるため。
        待たずに落とすと再生できないファイルが残る。
        """
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
            print("[WARN] 録画プロセスが終了しなかったため強制終了しました"
                  "（動画が再生できない可能性があります）")
            return
        if self._proc.returncode != 0:
            print(f"[WARN] 録画プロセスが異常終了しました "
                  f"(rc={self._proc.returncode}): {self._stderr_tail()}")

    def _stderr_tail(self, limit: int = 300) -> str:
        if self._proc.stderr is None:
            return ""
        try:
            return self._proc.stderr.read().decode("utf-8", "replace")[-limit:].strip()
        except OSError:
            return ""


def open_recorder(path: str, *, width: int, height: int, fps: float,
                  encoder: str = "auto", segment_bytes: int = 0,
                  max_segments: int = 0):
    """録画先を開く。

    Args:
        path: 出力パス。segment_bytes>0のときは連番を埋める書式
            （SEGMENT_PATTERNのように "%05d" を含むこと）。
        width, height: フレームの大きさ（実測値を渡すこと）
        fps: 書き出しfps
        encoder: "auto"（NVENCがあれば使い、無ければcv2）/ "nvenc" / "cv2"
        segment_bytes: 1本あたりの上限バイト数。0で分割しない。
        max_segments: 残す本数。0で無制限（古いものを消さない）。

    Returns:
        書き込み先。name属性に実際に選ばれたエンコーダ名が入る。

    Raises:
        ValueError: encoderが未知の値、"nvenc"指定でNVENCが使えない場合、
            または分割指定なのにpathが連番の書式を含まない場合。
    """
    if encoder not in ENCODER_CHOICES:
        raise ValueError(
            f"VIDEO_ENCODERは{'/'.join(ENCODER_CHOICES)}のいずれかです: {encoder!r}"
        )

    # 書式が無いまま分割すると、splitmuxsinkもcv2側も同じ名前へ上書きし続け、
    # 分割した意味が無くなる（しかも失敗として現れない）。
    if segment_bytes > 0 and "%" not in path:
        raise ValueError(
            f"分割するときは連番の書式を含むパスを渡してください: {path!r}"
        )

    # H.264は幅・高さが偶数である必要がある。奇数ならNVENCへ渡さない。
    even_size = width % 2 == 0 and height % 2 == 0

    want_nvenc = encoder in ("auto", "nvenc")
    if want_nvenc and even_size and nvenc_available():
        return NvencRecorder(
            path, width=width, height=height, fps=fps,
            segment_bytes=segment_bytes, max_segments=max_segments,
        )

    if encoder == "nvenc":
        reason = "幅・高さが偶数でない" if not even_size else "NVENCが利用できない"
        raise ValueError(
            f"VIDEO_ENCODER=nvencを指定しましたが使えません（{reason}）。"
            "autoにするとCPUエンコードへ切り替わります。"
        )

    if segment_bytes > 0:
        return Cv2SegmentedRecorder(
            path, width=width, height=height, fps=fps,
            segment_bytes=segment_bytes, max_segments=max_segments,
        )
    return Cv2Recorder(path, width=width, height=height, fps=fps)

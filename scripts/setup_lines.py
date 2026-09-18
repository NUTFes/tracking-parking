#!/usr/bin/env python3
"""
GUIライン座標設定ツール

動画の最初のフレームを表示し、マウスクリックで以下の5点を設定:
1. Line1(入口側)の始点
2. Line1(入口側)の終点
3. Line2(駐車場側)の始点
4. Line2(駐車場側)の終点
5. 駐車場基準点(駐車場内の任意の点)

設定完了後、.envファイルに自動保存
"""

import cv2
import argparse
import os
from typing import List, Tuple, Optional

from tracking_parking.common.camera import apply_camera_capture_settings
from tracking_parking.output.video_writer import LINE1_LABEL, LINE2_LABEL
from tracking_parking.config import CameraCaptureSettings

# カメラを開いた直後は露出が安定しない。捨てる枚数。
CAMERA_WARMUP_FRAMES = 10

LINE_ENV_KEYS = (
    "LINE1_START_X", "LINE1_START_Y", "LINE1_END_X", "LINE1_END_Y",
    "LINE2_START_X", "LINE2_START_Y", "LINE2_END_X", "LINE2_END_Y",
    "PARKING_REF_X", "PARKING_REF_Y",
)


def build_line_env_values(points: List[Tuple[int, int]]) -> dict:
    """クリックした5点をenvのキーと値へ変換する。

    順序は Line1始点 / Line1終点 / Line2始点 / Line2終点 / 駐車場基準点。
    """
    if len(points) != 5:
        raise ValueError(f"5点必要です: {len(points)}点")
    flat = [c for p in points for c in p]
    return dict(zip(LINE_ENV_KEYS, flat))


def apply_line_values(existing: str, values: dict) -> str:
    """既存の.env本文へライン値を反映した本文を返す。

    既存キーはその行だけを差し替え、無いキーは末尾のブロックへ追記する。
    コメント、並び順、他のキーはそのまま保つ。
    """
    remaining = dict(values)
    lines = existing.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# ライン座標（scripts/setup_lines.pyが書き込む）")
        for key in LINE_ENV_KEYS:
            if key in remaining:
                lines.append(f"{key}={remaining[key]}")

    return "\n".join(lines) + "\n"


class LineSetupGUI:
    """ライン座標設定GUI"""

    def __init__(self, video_path, env_path: str = None):
        """
        Args:
            video_path: 動画ファイルのパス(str)、またはカメラデバイスID(int)
            env_path: .envファイルのパス(Noneの場合はリポジトリルートの.envを使用)
        """
        self.video_path = video_path
        self.env_path = env_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env"
        )

        # クリックされた点を保存
        self.points: List[Tuple[int, int]] = []

        # 点のラベル（端末への案内用。ここは日本語が正しく出る）
        self.labels = [
            "Line1 始点(入口側)",
            "Line1 終点(入口側)",
            "Line2 始点(駐車場側)",
            "Line2 終点(駐車場側)",
            "駐車場基準点"
        ]

        # フレームへ焼き込む用。cv2.putTextのHersheyフォントはASCIIしか持たず、
        # 非ASCIIは1文字ずつ'?'になる（"Line1 始点(入口側)" → "Line1 ??(???)"）。
        # このOpenCVはfreetypeを含まないためTTF描画へ逃げられない。端末側の
        # self.labelsと1対1で対応させる（順序が同じであることをテストで固定）。
        self.overlay_labels = [
            "Line1 start (entry)",
            "Line1 end (entry)",
            "Line2 start (lot)",
            "Line2 end (lot)",
            "Parking reference"
        ]

        # 現在のフレーム
        self.frame: Optional[cv2.Mat] = None
        self.display_frame: Optional[cv2.Mat] = None

        # ウィンドウ名。非ASCIIにすると、このOpenCV(Qtバックエンド)では
        # namedWindowは通るのにsetMouseCallbackの名前引きがNULLを返して落ちる
        # （NULL window handler in setMouseCallbackImpl）。クリックが要なので
        # ここはASCIIで固定する。案内は端末側に日本語で出す。
        self.window_name = "Line Setup"

    def mouse_callback(self, event, x, y, flags, param):
        """
        マウスクリックのコールバック

        Args:
            event: イベントタイプ
            x, y: クリック座標
            flags: フラグ
            param: パラメータ
        """
        if event == cv2.EVENT_LBUTTONDOWN:
            # 左クリックで点を追加
            if len(self.points) < len(self.labels):
                self.points.append((x, y))
                print(f"✓ {self.labels[len(self.points) - 1]}: ({x}, {y})")

                # 表示を更新
                self.update_display()

                # 5点すべて設定完了
                if len(self.points) == len(self.labels):
                    print("\n全ての点が設定されました!")
                    print("確認してください。問題なければウィンドウを閉じてください。")
                    print("やり直す場合は'r'キーを押してください。")

    def update_display(self):
        """表示を更新"""
        self.display_frame = self.frame.copy()

        # 設定済みの点を描画
        for i, point in enumerate(self.points):
            color = (0, 255, 0) if i < 4 else (255, 0, 255)  # Line点=緑、基準点=マゼンタ
            cv2.circle(self.display_frame, point, 5, color, -1)
            cv2.putText(
                self.display_frame,
                self.overlay_labels[i],
                (point[0] + 10, point[1]),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )

        # Line1を描画
        if len(self.points) >= 2:
            cv2.line(
                self.display_frame,
                self.points[0],
                self.points[1],
                (0, 255, 0),  # 緑
                2
            )
            cv2.putText(
                self.display_frame,
                LINE1_LABEL,
                ((self.points[0][0] + self.points[1][0]) // 2,
                 (self.points[0][1] + self.points[1][1]) // 2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

        # Line2を描画
        if len(self.points) >= 4:
            cv2.line(
                self.display_frame,
                self.points[2],
                self.points[3],
                (0, 255, 255),  # 黄色
                2
            )
            cv2.putText(
                self.display_frame,
                LINE2_LABEL,
                ((self.points[2][0] + self.points[3][0]) // 2,
                 (self.points[2][1] + self.points[3][1]) // 2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2
            )

        # 次にクリックする点の説明を表示（焼き込むのでASCII側を使う）
        if len(self.points) < len(self.labels):
            instruction = f"Next: click {self.overlay_labels[len(self.points)]}"
            cv2.putText(
                self.display_frame,
                instruction,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )

        cv2.imshow(self.window_name, self.display_frame)

    def _window_closed(self) -> bool:
        """ウィンドウが閉じられたかを返す。

        ウィンドウマネージャの×で閉じられると、このOpenCV(Qtバックエンド)では
        getWindowPropertyが0を返さずに例外を投げる（NULL guiReceiver）。
        5点クリック後にウィンドウを閉じるのは保存を確定する正規の手順なので、
        ここで例外が抜けると座標が保存されないまま落ちる。閉じられたものとして扱う。
        """
        try:
            return cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1
        except cv2.error:
            return True

    def load_first_frame(self) -> bool:
        """
        ライン設定に使うフレームを1枚読み込む

        カメラ入力のときは、検知ループと同じ解像度を要求してから掴む。ここで
        掴んだフレーム上でクリックした座標がそのままLINE1_*/LINE2_*になるため、
        実行時の解像度と違うと座標の意味が変わる。

        Returns:
            bool: 成功した場合True
        """
        is_camera = not isinstance(self.video_path, str)
        cap = cv2.VideoCapture(self.video_path)

        if not cap.isOpened():
            target = f"カメラ{self.video_path}" if is_camera else self.video_path
            print(f"エラー: 映像を開けません: {target}")
            return False

        if is_camera:
            camera = CameraCaptureSettings.from_env(self.env_path)
            errors = camera.validation_errors()
            if errors:
                cap.release()
                print("設定エラー:\n" + "\n".join(f"  - {e}" for e in errors))
                return False
            apply_camera_capture_settings(
                cap, width=camera.width, height=camera.height, fourcc=camera.fourcc
            )
            # 開いた直後は露出が安定せず、暗いフレームでラインを引くことになる。
            for _ in range(CAMERA_WARMUP_FRAMES):
                cap.read()

        ret, frame = cap.read()
        actual = (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        cap.release()

        if not ret:
            target = f"カメラ{self.video_path}" if is_camera else self.video_path
            print(f"エラー: フレームを読み込めません: {target}")
            return False

        if is_camera:
            print(f"✓ カメラ{self.video_path}から取得: {actual[0]}x{actual[1]}")
            # 要求が丸められたまま座標を決めると、検知ループ側も同じ解像度で
            # 開くとは限らず（別のenvを使うなど）、ずれに気づけない。
            if camera.width is not None and actual != (camera.width, camera.height):
                print(
                    f"[WARN] カメラが要求解像度を受理しませんでした: "
                    f"要求 {camera.width}x{camera.height} → 実際 {actual[0]}x{actual[1]}"
                )

        self.frame = frame
        self.display_frame = frame.copy()

        return True

    def run(self) -> bool:
        """
        GUIを実行

        Returns:
            bool: 成功した場合True
        """
        # 最初のフレームを読み込み
        if not self.load_first_frame():
            return False

        # ウィンドウを作成
        cv2.namedWindow(self.window_name)
        cv2.imshow(self.window_name, self.display_frame)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        print("=" * 60)
        print("ライン座標設定ツール")
        print("=" * 60)
        print("\n以下の順番で5点をクリックしてください:\n")
        for i, label in enumerate(self.labels, 1):
            print(f"  {i}. {label}")
        print("\n操作:")
        print("  - 左クリック: 点を設定")
        print("  - 'r'キー: やり直し")
        print("  - 'q'キーまたはウィンドウを閉じる: 終了")
        print("=" * 60)

        self.update_display()

        while True:
            key = cv2.waitKey(1) & 0xFF

            # 'q'キーまたはウィンドウが閉じられた
            if key == ord('q') or self._window_closed():
                break

            # 'r'キーでやり直し
            if key == ord('r'):
                print("\nやり直します...")
                self.points = []
                self.update_display()
                print("\n以下の順番で5点をクリックしてください:")
                for i, label in enumerate(self.labels, 1):
                    print(f"  {i}. {label}")

        cv2.destroyAllWindows()

        # 5点すべて設定されているかチェック
        if len(self.points) != len(self.labels):
            print(f"\n警告: 5点すべてが設定されていません({len(self.points)}/5)")
            return False

        return True

    def save_to_env(self):
        """ライン座標だけを.envへ書き戻す。

        他のキー、コメント、並び順は保持する。以前はファイル全体をテンプレートで
        上書きしており、比較条件のために手で入れた値が消えていた。
        """
        values = build_line_env_values(self.points)

        if os.path.exists(self.env_path):
            existing = open(self.env_path, encoding="utf-8").read()
        else:
            template = os.path.join(os.path.dirname(self.env_path), ".env.template")
            existing = open(template, encoding="utf-8").read() if os.path.exists(template) else ""

        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(apply_line_values(existing, values))

        print(f"\n✓ ライン座標を保存しました: {self.env_path}")
        print("  （他のキーは変更していません）")
        print("\n設定内容:")
        print(f"  Line1 (入口側): {self.points[0]} → {self.points[1]}")
        print(f"  Line2 (駐車場側): {self.points[2]} → {self.points[3]}")
        print(f"  駐車場基準点: {self.points[4]}")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="GUIでライン座標を設定"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--video",
        help="動画ファイルのパス"
    )
    source.add_argument(
        "--camera",
        type=int,
        help="カメラデバイスID(0=デフォルトカメラ)。"
             "解像度は--envのCAMERA_WIDTH/HEIGHT/FOURCCに従う"
    )
    parser.add_argument(
        "--env",
        default=None,
        help=".envファイルのパス(デフォルト: リポジトリルートの.env)"
    )

    args = parser.parse_args()

    # 動画ファイルの存在確認
    if args.video is not None and not os.path.exists(args.video):
        print(f"エラー: 動画ファイルが見つかりません: {args.video}")
        return 1

    # GUIを実行
    gui = LineSetupGUI(args.video if args.video is not None else args.camera, args.env)

    if gui.run():
        # 設定を保存
        gui.save_to_env()
        print("\n完了!")
        return 0
    else:
        print("\nキャンセルされました。")
        return 1


if __name__ == "__main__":
    exit(main())

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

    def __init__(self, video_path: str, env_path: str = None):
        """
        Args:
            video_path: 動画ファイルのパス
            env_path: .envファイルのパス(Noneの場合はリポジトリルートの.envを使用)
        """
        self.video_path = video_path
        self.env_path = env_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env"
        )

        # クリックされた点を保存
        self.points: List[Tuple[int, int]] = []

        # 点のラベル
        self.labels = [
            "Line1 始点(入口側)",
            "Line1 終点(入口側)",
            "Line2 始点(駐車場側)",
            "Line2 終点(駐車場側)",
            "駐車場基準点"
        ]

        # 現在のフレーム
        self.frame: Optional[cv2.Mat] = None
        self.display_frame: Optional[cv2.Mat] = None

        # ウィンドウ名
        self.window_name = "ライン座標設定"

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
                self.labels[i],
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
                "Line1 (入口側)",
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
                "Line2 (駐車場側)",
                ((self.points[2][0] + self.points[3][0]) // 2,
                 (self.points[2][1] + self.points[3][1]) // 2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2
            )

        # 次にクリックする点の説明を表示
        if len(self.points) < len(self.labels):
            instruction = f"次: {self.labels[len(self.points)]} をクリック"
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

    def load_first_frame(self) -> bool:
        """
        動画の最初のフレームを読み込む

        Returns:
            bool: 成功した場合True
        """
        cap = cv2.VideoCapture(self.video_path)

        if not cap.isOpened():
            print(f"エラー: 動画ファイルを開けません: {self.video_path}")
            return False

        ret, frame = cap.read()
        cap.release()

        if not ret:
            print(f"エラー: 動画フレームを読み込めません: {self.video_path}")
            return False

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
            if key == ord('q') or cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
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

        他のキー、コメント、並び順は保持する（roi-counterのroi_config.pyと
        同じ契約）。以前はファイル全体をテンプレートで上書きしており、
        比較条件のために手で入れた値が消えていた。
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
    parser.add_argument(
        "--video",
        required=True,
        help="動画ファイルのパス"
    )
    parser.add_argument(
        "--env",
        default=None,
        help=".envファイルのパス(デフォルト: リポジトリルートの.env)"
    )

    args = parser.parse_args()

    # 動画ファイルの存在確認
    if not os.path.exists(args.video):
        print(f"エラー: 動画ファイルが見つかりません: {args.video}")
        return 1

    # GUIを実行
    gui = LineSetupGUI(args.video, args.env)

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

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


class LineSetupGUI:
    """ライン座標設定GUI"""

    def __init__(self, video_path: str, env_path: str = None):
        """
        Args:
            video_path: 動画ファイルのパス
            env_path: .envファイルのパス(Noneの場合はline_detection/.envを使用)
        """
        self.video_path = video_path
        self.env_path = env_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
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
        """設定を.envファイルに保存"""
        # 環境変数の内容を作成
        env_content = f"""# プロジェクトパス
HOME_DIR={os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))}

# YOLOモデル
MODEL_PATH=${{HOME_DIR}}/yolo_fine_tuning/runs/detect/train14/weights/best.pt
CONFIDENCE_THRESHOLD=0.3

# Line1設定(入口側ライン)
LINE1_START_X={self.points[0][0]}
LINE1_START_Y={self.points[0][1]}
LINE1_END_X={self.points[1][0]}
LINE1_END_Y={self.points[1][1]}

# Line2設定(駐車場側ライン)
LINE2_START_X={self.points[2][0]}
LINE2_START_Y={self.points[2][1]}
LINE2_END_X={self.points[3][0]}
LINE2_END_Y={self.points[3][1]}

# 駐車場基準点(駐車場側を定義)
PARKING_REF_X={self.points[4][0]}
PARKING_REF_Y={self.points[4][1]}

# 検知パラメータ
MARGIN_PX=5.0
ENDPOINT_MARGIN_PX=0.0
MAX_FRAME_GAP_SEC=3.0      # 秒。動画のfpsからフレーム数へ変換する
CLEANUP_THRESHOLD=150      # 5秒@30fps

# 処理方式: hybrid固定
METHOD=hybrid

# 出力設定
SAVE_VIDEO=true
SAVE_LOGS=true
SHOW_DISPLAY=false
"""

        # .envファイルに書き込み
        with open(self.env_path, 'w', encoding='utf-8') as f:
            f.write(env_content)

        print(f"\n✓ 設定を保存しました: {self.env_path}")
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
        help=".envファイルのパス(デフォルト: line_detection/.env)"
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

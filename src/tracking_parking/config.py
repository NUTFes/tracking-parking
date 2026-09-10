"""
設定管理モジュール
.envファイルから設定を読み込み、Configオブジェクトとして提供する
"""

import os
from dataclasses import dataclass
from typing import Tuple
from dotenv import load_dotenv


@dataclass
class Line:
    """ライン情報を保持するデータクラス"""
    start: Tuple[float, float]  # (x, y)
    end: Tuple[float, float]    # (x, y)

    def __post_init__(self):
        """座標を float に変換"""
        self.start = (float(self.start[0]), float(self.start[1]))
        self.end = (float(self.end[0]), float(self.end[1]))


@dataclass
class Config:
    """2ライン検知システムの設定を保持するクラス"""

    # プロジェクトパス
    home_dir: str

    # YOLOモデル設定
    model_path: str
    confidence_threshold: float
    vehicle_classes: list  # 検出する車両クラスIDのリスト

    # ライン設定
    line1: Line  # 入口側ライン(主判定)
    line2: Line  # 駐車場側ライン(補助)
    parking_ref_point: Tuple[float, float]  # 駐車場基準点

    # 検知パラメータ
    margin_px: float  # 判定保留帯の半幅(px)
    endpoint_margin_px: float  # 有限線分判定における端点の許容量(px)
    # 時間窓は秒で持ち、動画のfpsからフレーム数へ変換する
    # （common/time_windows.py の frames_from_seconds）。フレーム数で直接持つと、
    # 同じ設定値が撮影fpsによって別の長さを意味してしまう。
    max_frame_gap_sec: float  # Line1とLine2の通過を対応付ける最大の時間差(秒)
    cleanup_threshold_sec: float  # 古い追跡をクリーンアップするまでの未更新時間(秒)
    iou_threshold: float  # トラッキングのIOU閾値

    # 処理方式
    method: str  # "hybrid" 固定

    # 出力設定
    save_video: bool
    save_logs: bool
    show_display: bool

    @classmethod
    def from_env(cls, env_path: str = None):
        """
        .envファイルから設定を読み込む

        Args:
            env_path: .envファイルのパス(Noneの場合はカレントディレクトリから検索)

        Returns:
            Config: 設定オブジェクト
        """
        # .envファイルを読み込み
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()

        # プロジェクトパス
        home_dir = os.getenv("HOME_DIR")
        if not home_dir:
            raise ValueError("HOME_DIR が .env に設定されていません")

        # YOLOモデル設定
        model_path = os.getenv("MODEL_PATH")
        if not model_path:
            raise ValueError("MODEL_PATH が .env に設定されていません")

        confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.3"))

        # 車両クラス設定
        vehicle_classes_str = os.getenv("VEHICLE_CLASSES", "2,3,5,7")
        vehicle_classes = [int(x.strip()) for x in vehicle_classes_str.split(",")]

        # Line1設定(入口側)
        line1 = Line(
            start=(
                int(os.getenv("LINE1_START_X", "0")),
                int(os.getenv("LINE1_START_Y", "0"))
            ),
            end=(
                int(os.getenv("LINE1_END_X", "0")),
                int(os.getenv("LINE1_END_Y", "0"))
            )
        )

        # Line2設定(駐車場側)
        line2 = Line(
            start=(
                int(os.getenv("LINE2_START_X", "0")),
                int(os.getenv("LINE2_START_Y", "0"))
            ),
            end=(
                int(os.getenv("LINE2_END_X", "0")),
                int(os.getenv("LINE2_END_Y", "0"))
            )
        )

        # 駐車場基準点
        parking_ref_point = (
            float(os.getenv("PARKING_REF_X", "0")),
            float(os.getenv("PARKING_REF_Y", "0"))
        )

        # 検知パラメータ
        if os.getenv("MARGIN") is not None and os.getenv("MARGIN_PX") is None:
            raise ValueError(
                "MARGIN は廃止されました。MARGIN_PX(単位: px)へ移行してください。\n"
                "  旧: MARGIN=10.0 は外積値(距離×ライン長)との比較でした。\n"
                "  新: MARGIN_PX は signed_distance との比較で、単位が px そのものです。\n"
                "  数値をそのまま引き継ぐことはできません(ラインごとに換算係数が異なるため)。\n"
                "  .env の MARGIN 行を削除し、MARGIN_PX と ENDPOINT_MARGIN_PX を追加してください。"
            )
        margin_px = float(os.getenv("MARGIN_PX", "5.0"))
        endpoint_margin_px = float(os.getenv("ENDPOINT_MARGIN_PX", "0.0"))
        for old_name, new_name, old_example, new_example in (
            ("MAX_FRAME_GAP", "MAX_FRAME_GAP_SEC", "90", "3.0"),
            ("CLEANUP_THRESHOLD", "CLEANUP_THRESHOLD_SEC", "150", "5.0"),
        ):
            if os.getenv(old_name) is not None and os.getenv(new_name) is None:
                raise ValueError(
                    f"{old_name} は廃止されました。{new_name}(単位: 秒)へ移行してください。\n"
                    f"  旧: {old_name}={old_example} はフレーム数で、30fpsを前提とした値でした。\n"
                    f"  新: {new_name} は秒で指定し、動画のfpsからフレーム数へ変換します。\n"
                    f"  30fps相当の設定は {new_name}={new_example} です。\n"
                    f"  .env の {old_name} 行を {new_name} へ書き換えてください。"
                )
        max_frame_gap_sec = float(os.getenv("MAX_FRAME_GAP_SEC", "3.0"))
        cleanup_threshold_sec = float(os.getenv("CLEANUP_THRESHOLD_SEC", "5.0"))
        iou_threshold = float(os.getenv("IOU_THRESHOLD", "0.3"))

        # 処理方式
        method = os.getenv("METHOD", "hybrid")

        # 出力設定
        save_video = os.getenv("SAVE_VIDEO", "true").lower() == "true"
        save_logs = os.getenv("SAVE_LOGS", "true").lower() == "true"
        show_display = os.getenv("SHOW_DISPLAY", "false").lower() == "true"

        return cls(
            home_dir=home_dir,
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            vehicle_classes=vehicle_classes,
            line1=line1,
            line2=line2,
            parking_ref_point=parking_ref_point,
            margin_px=margin_px,
            endpoint_margin_px=endpoint_margin_px,
            max_frame_gap_sec=max_frame_gap_sec,
            cleanup_threshold_sec=cleanup_threshold_sec,
            iou_threshold=iou_threshold,
            method=method,
            save_video=save_video,
            save_logs=save_logs,
            show_display=show_display
        )

    def validate(self):
        """設定値の妥当性をチェック"""
        errors = []

        # モデルパスの存在確認
        if not os.path.exists(self.model_path):
            errors.append(f"モデルファイルが見つかりません: {self.model_path}")

        # ライン座標のチェック
        if self.line1.start == self.line1.end:
            errors.append("Line1の始点と終点が同じです")

        if self.line2.start == self.line2.end:
            errors.append("Line2の始点と終点が同じです")

        # パラメータの範囲チェック
        if self.confidence_threshold < 0 or self.confidence_threshold > 1:
            errors.append(f"confidence_thresholdは0-1の範囲で設定してください: {self.confidence_threshold}")

        if self.margin_px < 0:
            errors.append(f"margin_pxは0以上の値である必要があります: {self.margin_px}")

        if self.endpoint_margin_px < 0:
            errors.append(f"endpoint_margin_pxは0以上の値である必要があります: {self.endpoint_margin_px}")

        if self.max_frame_gap_sec < 0:
            errors.append(f"max_frame_gap_secは0以上の値である必要があります: {self.max_frame_gap_sec}")

        if self.cleanup_threshold_sec < 0:
            errors.append(f"cleanup_threshold_secは0以上の値である必要があります: {self.cleanup_threshold_sec}")

        # 処理方式のチェック
        if self.method != "hybrid":
            errors.append(f"methodは'hybrid'である必要があります: {self.method}")

        if errors:
            raise ValueError("設定エラー:\n" + "\n".join(f"  - {e}" for e in errors))

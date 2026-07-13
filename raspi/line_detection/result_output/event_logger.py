"""
イベントログ出力モジュール
検知イベントをJSON/CSV形式で保存
"""

import json
import csv
import os
from datetime import datetime
from typing import List, Dict, Any


class Event:
    """イベントデータクラス"""

    def __init__(self,
                 track_id: int,
                 event_type: str,
                 frame_id: int,
                 timestamp_sec: float,
                 confidence: str,
                 line2_crossed: bool):
        """
        Args:
            track_id: トラッキングID
            event_type: イベントタイプ("IN" or "OUT")
            frame_id: フレーム番号
            timestamp_sec: タイムスタンプ(秒)
            confidence: 信頼度("high" or "normal")
            line2_crossed: Line2を交差したか
        """
        self.track_id = track_id
        self.event_type = event_type
        self.frame_id = frame_id
        self.timestamp_sec = timestamp_sec
        self.confidence = confidence
        self.line2_crossed = line2_crossed

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "track_id": self.track_id,
            "event_type": self.event_type,
            "frame_id": self.frame_id,
            "timestamp_sec": round(self.timestamp_sec, 2),
            "confidence": self.confidence,
            "line2_crossed": self.line2_crossed
        }


class EventLogger:
    """イベントログ出力クラス"""

    def __init__(self, video_path: str = None):
        """
        Args:
            video_path: 動画ファイルのパス
        """
        self.video_path = video_path
        self.events: List[Event] = []
        self.start_time = datetime.now()
        self.total_frames = 0
        self.total_processing_time_ms = 0.0

    def record_event(self,
                    track_id: int,
                    event_type: str,
                    frame_id: int,
                    fps: float,
                    confidence: str,
                    line2_crossed: bool):
        """
        イベントを記録

        Args:
            track_id: トラッキングID
            event_type: イベントタイプ("IN" or "OUT")
            frame_id: フレーム番号
            fps: FPS
            confidence: 信頼度("high" or "normal")
            line2_crossed: Line2を交差したか
        """
        timestamp_sec = frame_id / fps if fps > 0 else 0.0

        event = Event(
            track_id=track_id,
            event_type=event_type,
            frame_id=frame_id,
            timestamp_sec=timestamp_sec,
            confidence=confidence,
            line2_crossed=line2_crossed
        )

        self.events.append(event)

    def record_frame_time(self, processing_time_ms: float):
        """
        フレーム処理時間を記録

        Args:
            processing_time_ms: 処理時間(ms)
        """
        self.total_processing_time_ms += processing_time_ms
        self.total_frames += 1

    def get_summary(
        self,
        tracker_summary: Dict,
        timing_summary: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        サマリーを取得

        Args:
            tracker_summary: VehicleTrackerのサマリー

        Returns:
            Dict: サマリー情報
        """
        avg_time = (
            timing_summary["core_ms_mean"]
            if timing_summary is not None
            else self.total_processing_time_ms / self.total_frames
            if self.total_frames > 0
            else 0.0
        )

        return {
            "total_in": tracker_summary["total_in"],
            "total_out": tracker_summary["total_out"],
            "current_parked": tracker_summary["current_parked"],
            "high_confidence_events": tracker_summary["high_confidence_events"],
            "normal_confidence_events": tracker_summary["normal_confidence_events"],
            "avg_processing_time_ms": round(avg_time, 2)
        }

    def save_json(
        self,
        output_dir: str,
        tracker_summary: Dict,
        wandb_run_id: str = None,
        execution_id: str = None,
        condition_key: str = None,
        exp_key: str = None,
        timing_summary: Dict[str, Any] = None,
    ) -> str:
        """
        JSONファイルに保存

        Args:
            output_dir: 出力ディレクトリ
            tracker_summary: VehicleTrackerのサマリー
            wandb_run_id: W&Bが発行したrun ID（無効時はNone）
            execution_id: 実行ごとのUUID
            condition_key: 条件のcanonical JSONから生成したhash
            exp_key: condition_keyの後方互換alias

        Returns:
            str: 保存したファイルのパス
        """
        # 出力ディレクトリを作成
        os.makedirs(output_dir, exist_ok=True)

        # ファイル名を生成
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"events_{timestamp}.json"
        filepath = os.path.join(output_dir, filename)

        # JSONデータを作成
        data = {
            "video_path": self.video_path or "unknown",
            "processed_at": self.start_time.isoformat(),
            "total_frames": self.total_frames,
            "avg_processing_time_ms": round(
                timing_summary["core_ms_mean"]
                if timing_summary is not None
                else self.total_processing_time_ms / self.total_frames
                if self.total_frames > 0
                else 0.0,
                2
            ),
            "events": [event.to_dict() for event in self.events],
            "summary": self.get_summary(tracker_summary, timing_summary)
        }
        if timing_summary is not None:
            data["timing"] = timing_summary
        if wandb_run_id is not None:
            data["wandb_run_id"] = wandb_run_id
        if execution_id is not None:
            data["execution_id"] = execution_id
        if condition_key is not None:
            data["condition_key"] = condition_key
        if exp_key is not None:
            data["exp_key"] = exp_key

        # JSONファイルに書き込み
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"✓ JSONログを保存: {filepath}")
        return filepath

    def save_csv(self, output_dir: str) -> str:
        """
        CSVファイルに保存

        Args:
            output_dir: 出力ディレクトリ

        Returns:
            str: 保存したファイルのパス
        """
        # 出力ディレクトリを作成
        os.makedirs(output_dir, exist_ok=True)

        # ファイル名を生成
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"events_{timestamp}.csv"
        filepath = os.path.join(output_dir, filename)

        # CSVファイルに書き込み
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            if len(self.events) == 0:
                # イベントがない場合はヘッダーのみ
                writer = csv.writer(f)
                writer.writerow([
                    "track_id",
                    "event_type",
                    "frame_id",
                    "timestamp_sec",
                    "confidence",
                    "line2_crossed"
                ])
            else:
                # イベントがある場合
                fieldnames = [
                    "track_id",
                    "event_type",
                    "frame_id",
                    "timestamp_sec",
                    "confidence",
                    "line2_crossed"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                # ヘッダーを書き込み
                writer.writeheader()

                # イベントを書き込み
                for event in self.events:
                    writer.writerow(event.to_dict())

        print(f"✓ CSVログを保存: {filepath}")
        return filepath

    def print_summary(
        self,
        tracker_summary: Dict,
        timing_summary: Dict[str, Any] = None,
    ):
        """
        サマリーを出力

        Args:
            tracker_summary: VehicleTrackerのサマリー
        """
        summary = self.get_summary(tracker_summary, timing_summary)

        print("\n" + "=" * 60)
        print("処理結果サマリー")
        print("=" * 60)
        print(f"入庫: {summary['total_in']}")
        print(f"出庫: {summary['total_out']}")
        print(f"現在駐車台数: {summary['current_parked']}")
        print(f"高信頼度イベント: {summary['high_confidence_events']}")
        print(f"通常信頼度イベント: {summary['normal_confidence_events']}")
        print(f"平均処理時間: {summary['avg_processing_time_ms']:.2f}ms/frame")
        print("=" * 60)

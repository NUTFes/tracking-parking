"""
Weights & Biases 連携の薄いラッパ（両検出ロジック共通）

- W&B 無効時（enabled=False）は wandb を一切 import せず、全メソッドが no-op。
  → wandb 未インストール環境・CI・オフライン実行で既存挙動と完全一致する。
- WANDB_MODE（online/offline）は wandb 側の標準挙動に委譲（本ラッパで上書きしない）。
  オフライン計測 → 後日 `wandb sync <run_dir>` でアップロードできる。
- `build_exp_key()` は両ロジック・後追い評価スクリプトが必ず共有する突合キー生成関数。
"""

import json
import math
from pathlib import Path
from typing import Optional, List, Dict, Any


# 後追い（SAM3 GT 突合後）で埋める精度系 summary キー。今は None で確保する。
ACCURACY_PLACEHOLDER_KEYS = [
    "accuracy",
    "precision",
    "recall",
    "f1",
    "tp",
    "fp",
    "fn",
    "tn",
    "eval_unit",
    "gt_source",
]


def build_exp_key(logic_name: str, dataset: str, device_name: str, params: Dict[str, Any]) -> str:
    """
    run を一意に再特定するための複合キーを生成する（全スクリプト共通）。

    形式: f"{logic_name}__{dataset}__{param_str}__{device_name}"
        param_str は params をキー名の昇順ソートで "k1=v1_k2=v2" に正規化する
        （float は f"{v:g}"）。

    各スクリプトで独自フォーマットを組み立ててはならない（突合キーとして機能しなくなるため）。
    """
    parts = []
    for key in sorted(params.keys()):
        value = params[key]
        if isinstance(value, float):
            value_str = f"{value:g}"
        else:
            value_str = str(value)
        parts.append(f"{key}={value_str}")
    param_str = "_".join(parts)
    return f"{logic_name}__{dataset}__{param_str}__{device_name}"


def validate_log_interval_sec(raw_value: Any, *, source: str = "LOG_INTERVAL_SEC") -> float:
    """LOG_INTERVAL_SEC の生値（文字列 or 数値）をパース・検証する。

    0・負数・NaN・inf・数値変換不能な文字列をすべて ValueError で明示的に拒否する。
    """
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f"{source} must be a positive finite number, got {raw_value!r}")
    if math.isnan(value) or math.isinf(value) or value <= 0:
        raise ValueError(f"{source} must be a positive finite number, got {raw_value!r}")
    return value


def next_log_boundary(next_log_sec: float, t_rel_sec: float, log_interval_sec: float) -> float:
    """次の定期サンプリング境界を while ループなし（O(1)）で計算する。

    t_rel_sec == next_log_sec の場合も「ログ済み」として1区間進める（旧 `<=` 意味論を維持）。
    count_changed による早期ログでも、この関数は t_rel_sec のみから境界を計算するため、
    定期的なサンプリング間隔がずれることはない。
    """
    steps = math.floor((t_rel_sec - next_log_sec) / log_interval_sec) + 1
    return next_log_sec + steps * log_interval_sec


def should_log_frame(t_rel_sec: float, next_log_sec: float, count_changed: bool) -> bool:
    """このフレームで log_frame すべきか判定する（副作用なし）。"""
    return t_rel_sec >= next_log_sec or count_changed


class ExperimentLogger:
    """W&B 連携ラッパ。enabled=False で完全 no-op になる。"""

    def __init__(
        self,
        project: str,
        config: Dict[str, Any],
        group: str,
        job_type: str,
        tags: List[str],
        enabled: bool,
    ):
        """
        Args:
            project: W&B プロジェクト名
            config: run 開始時に固定するスカラ設定（exp_key を含む）
            group: run のグループ（= logic_name）
            job_type: "speed_eval" / "accuracy_eval" 等
            tags: device_name, input_type 等
            enabled: False のとき wandb.init を呼ばず全メソッドを no-op にする
        """
        self.enabled = enabled
        self._wandb = None
        self._run = None
        self._exp_key = config.get("exp_key") if config else None

        if not self.enabled:
            return

        # 遅延 import: enabled のときだけ読み込む（未インストール環境で落ちないように）。
        import wandb

        self._wandb = wandb
        self._run = wandb.init(
            project=project,
            config=config,
            group=group,
            job_type=job_type,
            tags=tags,
        )

    @property
    def run_id(self) -> Optional[str]:
        """wandb.run.id（無効時は None）。"""
        if not self.enabled or self._run is None:
            return None
        return self._run.id

    def define_metric(self, name: str, step_metric: str) -> None:
        """時系列メトリクスの x 軸を step_metric（例: t_rel_sec）に宣言する。"""
        if not self.enabled:
            return
        self._wandb.define_metric(name, step_metric=step_metric)

    def log_frame(self, step: int, metrics: Dict[str, Any]) -> None:
        """時系列メトリクスを log する（step は単調増加の実フレーム番号）。"""
        if not self.enabled:
            return
        self._wandb.log(metrics, step=step)

    def set_summary(self, key: str, value: Any) -> None:
        """summary に単一スカラを設定する。"""
        if not self.enabled:
            return
        self._run.summary[key] = value

    def set_summaries(self, d: Dict[str, Any]) -> None:
        """summary に複数スカラをまとめて設定する。"""
        if not self.enabled:
            return
        for key, value in d.items():
            self._run.summary[key] = value

    def update_running_summary(self, d: Dict[str, Any]) -> None:
        """処理途中の集計（count_in/out 等）を summary へ随時反映する。

        長時間運用でクラッシュしても直近の集計が残るようにするための薄いメソッド。
        """
        self.set_summaries(d)

    def init_accuracy_placeholders(self) -> None:
        """精度系 summary キーを None で確保する（init 直後に呼ぶ）。

        後追いスクリプトが同じスキーマへ書き込めるようにするため。
        """
        if not self.enabled:
            return
        for key in ACCURACY_PLACEHOLDER_KEYS:
            self._run.summary[key] = None

    def finish(self, exit_code: int = 0) -> None:
        """run を finish する。異常終了時は exit_code=1 で呼ぶ（try/finally 必須）。"""
        if not self.enabled or self._run is None:
            return
        self._wandb.finish(exit_code=exit_code)

    def save_run_id(self, out_dir: Path) -> None:
        """out_dir/"wandb_run_id.txt" に run.id と exp_key を書き出す。"""
        if not self.enabled:
            return
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        text = f"wandb_run_id={self.run_id}\nexp_key={self._exp_key}\n"
        (out_dir / "wandb_run_id.txt").write_text(text, encoding="utf-8")

    def append_to_result_json(self, result_path: Path) -> None:
        """既存の result.json へ wandb_run_id / exp_key を追記する。

        ファイルが無い / 無効時は何もしない（後方互換）。
        """
        if not self.enabled:
            return
        result_path = Path(result_path)
        if not result_path.exists():
            return
        data = json.loads(result_path.read_text(encoding="utf-8"))
        data["wandb_run_id"] = self.run_id
        data["exp_key"] = self._exp_key
        result_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

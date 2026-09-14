"""実験runの条件識別子・実行識別子・再現情報・manifestを共通管理する。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


CONDITION_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
REPRODUCIBILITY_PACKAGES = (
    "numpy",
    "opencv-python",
    "pandas",
    "torch",
    "ultralytics",
    "wandb",
)


def _validate_mapping_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("condition keys must be strings")
        for nested in value.values():
            _validate_mapping_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _validate_mapping_keys(nested)


def canonical_condition_json(condition: Mapping[str, Any]) -> str:
    """JSONの型を保ったまま、辞書順に依存しないcanonical表現を返す。"""

    if not isinstance(condition, Mapping):
        raise TypeError("condition must be a mapping")
    _validate_mapping_keys(condition)
    return json.dumps(
        {
            "schema_version": CONDITION_SCHEMA_VERSION,
            "condition": condition,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_condition_key(condition: Mapping[str, Any]) -> str:
    """同じ条件なら同じ値になる、型付きcanonical JSON由来のキーを返す。"""

    payload = canonical_condition_json(condition).encode("utf-8")
    return f"ck{CONDITION_SCHEMA_VERSION}_{hashlib.sha256(payload).hexdigest()}"


def new_execution_id() -> str:
    """個々の実行を一意に識別するUUIDを返す。"""

    return str(uuid.uuid4())


def build_display_name(
    logic_name: str,
    dataset: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    """W&B UI等で使う、人が読めるが一意性を担わない表示名を返す。"""

    parts = [logic_name, dataset]
    if params:
        parts.extend(f"{key}={params[key]}" for key in sorted(params))
    return "__".join(parts)


def build_run_identity(
    condition: Mapping[str, Any],
    *,
    display_name: str,
    execution_id: str | None = None,
) -> dict[str, str]:
    """1 run分の条件キー・実行ID・表示名をまとめて返す。"""

    return {
        "condition_key": build_condition_key(condition),
        "execution_id": execution_id or new_execution_id(),
        "display_name": display_name,
    }


def _run_git(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.rstrip("\n")


def collect_reproducibility_info(repo_root: Path | None = None) -> dict[str, Any]:
    """Git状態と主要ライブラリ版をW&B configへ保存できる形で返す。"""

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    git_sha = _run_git(root, "rev-parse", "HEAD")
    git_status = _run_git(root, "status", "--porcelain", "--untracked-files=normal")
    git_diff = _run_git(root, "diff", "--binary", "HEAD")
    dirty = bool(git_status) if git_status is not None else None
    dirty_fingerprint = None
    if dirty:
        fingerprint_source = f"{git_status}\n{git_diff or ''}".encode("utf-8")
        dirty_fingerprint = hashlib.sha256(fingerprint_source).hexdigest()

    library_versions: dict[str, str | None] = {}
    for package in REPRODUCIBILITY_PACKAGES:
        try:
            library_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            library_versions[package] = None

    return {
        "git_sha": git_sha,
        "git_dirty": dirty,
        "git_dirty_fingerprint": dirty_fingerprint,
        "python_version": platform.python_version(),
        "library_versions": library_versions,
    }


def write_run_manifest(
    manifest_path: Path,
    *,
    config: Mapping[str, Any],
    output_dir: Path,
    output_paths: Sequence[Path | str],
    wandb_run_id: str | None,
) -> dict[str, Any]:
    """runとローカル出力を相互参照できるmanifestをJSONで保存する。"""

    required = ("condition_key", "execution_id", "display_name")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"config is missing run identity fields: {', '.join(missing)}")

    resolved_output_dir = Path(output_dir).resolve()
    resolved_outputs = []
    for output_path in output_paths:
        path = Path(output_path)
        if not path.is_absolute():
            path = resolved_output_dir / path
        resolved_outputs.append(str(path.resolve()))

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "condition_key": config["condition_key"],
        "execution_id": config["execution_id"],
        "wandb_run_id": wandb_run_id,
        "display_name": config["display_name"],
        "output_dir": str(resolved_output_dir),
        "output_paths": resolved_outputs,
        "config": dict(config),
    }
    target = Path(manifest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest

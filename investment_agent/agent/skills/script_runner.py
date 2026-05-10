import json
import subprocess
import sys
from pathlib import Path


def _ensure_subpath(base: Path, target: Path) -> None:
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise ValueError(f"entry path escapes skill dir: {target}")


def run_skill_entry(skill_dir: Path, entry: str, kwargs: dict, timeout_seconds: int = 20) -> str:
    entry_path = (skill_dir / entry).resolve()
    _ensure_subpath(skill_dir, entry_path)

    if entry_path.suffix != ".py":
        raise ValueError(f"only python entry is supported: {entry_path}")
    if not entry_path.exists() or not entry_path.is_file():
        raise ValueError(f"entry file not found: {entry_path}")

    payload = json.dumps(kwargs, ensure_ascii=False)
    proc = subprocess.run(
        [sys.executable, str(entry_path)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(skill_dir),
        timeout=timeout_seconds,
    )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "script failed").strip()
        raise RuntimeError(err)

    return (proc.stdout or "").strip()

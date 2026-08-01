import asyncio
import json
import sys
from pathlib import Path


def _ensure_subpath(base: Path, target: Path) -> None:
    """安全检查：确保入口脚本不逃逸 Skill 目录（防止路径穿越攻击）"""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise ValueError(f"entry path escapes skill dir: {target}")


def _kwargs_to_cli(kwargs: dict) -> list[str]:
    """将 Python kwargs 转为 CLI 参数列表：{"foo_bar": "val"} → ["--foo-bar", "val"]"""
    cli_args = []
    for key, value in kwargs.items():
        flag = "--" + key.replace("_", "-")
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                cli_args.append(flag)
        else:
            cli_args.append(flag)
            cli_args.append(str(value))
    return cli_args


async def run_skill_entry(skill_dir: Path, entry: str, kwargs: dict, timeout_seconds: int = 20) -> str:
    """通过子进程执行 Skill 的 Python 入口脚本

    安全措施：
    - 校验入口脚本在 skill_dir 目录内
    - 仅允许 .py 文件
    - 20 秒超时
    - kwargs 通过 CLI 参数 + stdin JSON 双通道传递
    """
    entry_path = (skill_dir / entry).resolve()
    _ensure_subpath(skill_dir, entry_path)

    if entry_path.suffix != ".py":
        raise ValueError(f"only python entry is supported: {entry_path}")
    if not entry_path.exists() or not entry_path.is_file():
        raise ValueError(f"entry file not found: {entry_path}")

    cli_args = _kwargs_to_cli(kwargs)
    payload = json.dumps(kwargs, ensure_ascii=False)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(entry_path),
        *cli_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(skill_dir),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload.encode("utf-8")),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"script timed out after {timeout_seconds}s") from exc

    stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
    stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

    if proc.returncode != 0:
        err = (stderr_text or stdout_text or "script failed").strip()
        raise RuntimeError(err)

    return stdout_text.strip()

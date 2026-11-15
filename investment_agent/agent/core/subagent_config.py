"""Subagent 运行时配置：分层解析（L2 定义 > L1 主 Agent > L0 全局 > 父主配置继承）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from ..constants import OffloadSummaryStrategy

# 子运行时可配置字段（与 UI / DB / Markdown frontmatter 对齐）
SUBAGENT_RUNTIME_FIELD_NAMES: tuple[str, ...] = (
    "token_budget",
    "max_single_turn_output_tokens",
    "runtime_context_compression_enabled",
    "context_trim_token_threshold",
    "offload_threshold",
    "offload_summary_strategy",
    "offload_summary_chars",
)

# 代码级常量兜底（解析链末端）
_DEFAULT_TOKEN_BUDGET = 100_000


@dataclass
class SubagentRuntimeOverrides:
    """某一配置层的部分覆盖；None = 本层未设置。"""

    token_budget: int | None = None
    max_single_turn_output_tokens: int | None = None  # 单轮 LLM 回复的最大输出 token
    runtime_context_compression_enabled: bool | None = None
    context_trim_token_threshold: int | None = None
    offload_threshold: int | None = None
    offload_summary_strategy: str | None = None
    offload_summary_chars: int | None = None

    def to_dict(self, *, omit_none: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if omit_none:
            return {k: v for k, v in data.items() if v is not None}
        return data


@dataclass
class ResolvedSubagentRuntimeConfig:
    """子引擎已解析的运行时参数（无「未设置」语义）。"""

    token_budget: int
    max_single_turn_output_tokens: int | None  # 单轮 LLM 回复的最大输出 token；传给 API 的 max_tokens
    runtime_context_compression_enabled: bool
    context_trim_token_threshold: int
    offload_threshold: int
    offload_summary_strategy: str
    offload_summary_chars: int
    # max_steps / loop_detection 不单独配置，创建子引擎时直接复用父 Agent

    @property
    def compression_active(self) -> bool:
        return (
            self.runtime_context_compression_enabled
            and self.context_trim_token_threshold > 0
        )


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return None


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_subagent_runtime_dict(raw: Any) -> dict[str, Any]:
    """将任意层原始值规范为仅含已知字段的 dict（值可为 None，键只保留有值项）。"""
    if not raw:
        return {}
    if isinstance(raw, SubagentRuntimeOverrides):
        return raw.to_dict(omit_none=True)
    if not isinstance(raw, dict):
        return {}

    # 兼容：嵌套 runtime_config / subagent 再包一层
    if "runtime_config" in raw and isinstance(raw.get("runtime_config"), dict):
        nested = dict(raw["runtime_config"])
        # 扁平键优先覆盖嵌套（便于 Markdown 扁平写法与对象并存）
        # 含历史别名，便于 frontmatter / 旧配置迁移
        for key in SUBAGENT_RUNTIME_FIELD_NAMES + ("max_output_tokens", "max_tokens"):
            if key in raw and raw[key] is not None and raw[key] != "":
                nested[key] = raw[key]
        raw = nested

    out: dict[str, Any] = {}
    # 兼容旧扁平别名
    token = raw.get("token_budget", raw.get("subagent_token_budget"))
    parsed_token = _as_optional_int(token)
    if parsed_token is not None:
        out["token_budget"] = parsed_token

    # max_single_turn_output_tokens；兼容 max_output_tokens / max_tokens
    parsed_out = _as_optional_int(
        raw.get(
            "max_single_turn_output_tokens",
            raw.get("max_output_tokens", raw.get("max_tokens")),
        )
    )
    if parsed_out is not None:
        out["max_single_turn_output_tokens"] = parsed_out

    for key, caster in (
        ("runtime_context_compression_enabled", _as_optional_bool),
        ("context_trim_token_threshold", _as_optional_int),
        ("offload_threshold", _as_optional_int),
        ("offload_summary_strategy", _as_optional_str),
        ("offload_summary_chars", _as_optional_int),
    ):
        if key not in raw:
            continue
        parsed = caster(raw.get(key))
        if parsed is not None:
            out[key] = parsed
    return out


def overrides_from_mapping(raw: Any) -> SubagentRuntimeOverrides:
    data = normalize_subagent_runtime_dict(raw)
    known = {f.name for f in fields(SubagentRuntimeOverrides)}
    return SubagentRuntimeOverrides(**{k: v for k, v in data.items() if k in known})


def extract_runtime_config_from_frontmatter(fields_map: dict[str, Any]) -> dict[str, Any]:
    """从 Markdown frontmatter 字段表提取 runtime_config（支持扁平键）。"""
    # 若显式给了 runtime_config JSON 字符串
    raw_rc = fields_map.get("runtime_config")
    if isinstance(raw_rc, str) and raw_rc.strip().startswith("{"):
        try:
            import json

            parsed = json.loads(raw_rc)
            if isinstance(parsed, dict):
                return normalize_subagent_runtime_dict({**parsed, **fields_map})
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if isinstance(raw_rc, dict):
        return normalize_subagent_runtime_dict({**raw_rc, **fields_map})
    return normalize_subagent_runtime_dict(fields_map)


def _pick(
    *layers: dict[str, Any],
    key: str,
    inherit: Any = None,
    default: Any = None,
) -> Any:
    """按层优先取值；各层均未设置时用 inherit，再否则 default。"""
    for layer in layers:
        if key in layer and layer[key] is not None:
            return layer[key]
    if inherit is not None:
        return inherit
    return default


def _parent_subagent_layer(parent: Any) -> dict[str, Any]:
    """L1：父引擎上的 subagent 默认块 + 旧扁平 subagent_token_budget。"""
    raw = getattr(parent, "subagent_runtime_defaults", None)
    if raw is None:
        raw = getattr(parent, "subagent", None)
    layer = normalize_subagent_runtime_dict(raw)
    if "token_budget" not in layer:
        flat = getattr(parent, "subagent_token_budget", None)
        parsed = _as_optional_int(flat)
        if parsed is not None:
            layer["token_budget"] = parsed
    return layer


def _global_subagent_layer() -> dict[str, Any]:
    """L0：settings.engine.subagent（可选）+ 扁平 subagent_token_budget。"""
    try:
        from ...config import get_settings

        engine = get_settings().get("engine") or {}
    except Exception:
        engine = {}
    layer = normalize_subagent_runtime_dict(engine.get("subagent"))
    if "token_budget" not in layer:
        parsed = _as_optional_int(engine.get("subagent_token_budget"))
        if parsed is not None:
            layer["token_budget"] = parsed
    return layer


def _definition_layer(definition: dict | None) -> dict[str, Any]:
    if not definition:
        return {}
    raw = definition.get("runtime_config")
    if raw is None:
        # 允许定义顶层直接带扁平运行时键
        return normalize_subagent_runtime_dict(definition)
    return normalize_subagent_runtime_dict(raw)


def resolve_subagent_runtime_config(
    parent: Any,
    definition: dict | None = None,
) -> ResolvedSubagentRuntimeConfig:
    """解析子引擎运行时配置。

    优先级（单字段）：L2 定义 > L1 父 engine_config.subagent > L0 全局 >
    父主配置继承 > 代码常量。
    """
    l2 = _definition_layer(definition)
    l1 = _parent_subagent_layer(parent)
    l0 = _global_subagent_layer()

    parent_compression = bool(
        getattr(parent, "runtime_context_compression_enabled", True)
    )
    parent_trim = int(getattr(parent, "context_trim_token_threshold", 0) or 0)
    parent_offload_threshold = int(getattr(parent, "offload_threshold", 800) or 800)
    parent_offload_strategy = (
        getattr(parent, "offload_summary_strategy", None)
        or OffloadSummaryStrategy.TRUNCATE
    )
    parent_offload_chars = int(getattr(parent, "offload_summary_chars", 200) or 200)
    parent_single_turn_output = getattr(parent, "max_tokens", None)

    token_budget = int(
        _pick(
            l2, l1, l0,
            key="token_budget",
            default=_DEFAULT_TOKEN_BUDGET,
        )
    )
    max_single_turn_output_tokens = _pick(
        l2, l1, l0,
        key="max_single_turn_output_tokens",
        inherit=parent_single_turn_output,
        default=None,
    )
    if max_single_turn_output_tokens is not None:
        max_single_turn_output_tokens = int(max_single_turn_output_tokens)

    compression_enabled = bool(
        _pick(
            l2, l1, l0,
            key="runtime_context_compression_enabled",
            inherit=parent_compression,
            default=True,
        )
    )
    trim_threshold = int(
        _pick(
            l2, l1, l0,
            key="context_trim_token_threshold",
            inherit=parent_trim,
            default=0,
        )
    )
    if not compression_enabled:
        trim_threshold = 0

    offload_threshold = int(
        _pick(
            l2, l1, l0,
            key="offload_threshold",
            inherit=parent_offload_threshold,
            default=800,
        )
    )
    offload_strategy = str(
        _pick(
            l2, l1, l0,
            key="offload_summary_strategy",
            inherit=parent_offload_strategy,
            default=OffloadSummaryStrategy.TRUNCATE,
        )
    )
    offload_chars = int(
        _pick(
            l2, l1, l0,
            key="offload_summary_chars",
            inherit=parent_offload_chars,
            default=200,
        )
    )

    # 合理边界
    token_budget = max(1_000, int(token_budget))

    return ResolvedSubagentRuntimeConfig(
        token_budget=token_budget,
        max_single_turn_output_tokens=max_single_turn_output_tokens,
        runtime_context_compression_enabled=compression_enabled,
        context_trim_token_threshold=trim_threshold,
        offload_threshold=offload_threshold,
        offload_summary_strategy=offload_strategy,
        offload_summary_chars=offload_chars,
    )


def build_child_runtime_compressor(
    parent: Any,
    resolved: ResolvedSubagentRuntimeConfig,
    *,
    parent_session_id: str,
    child_session_id: str,
):
    """按解析结果构造子引擎 RuntimeCompressor。"""
    import os

    from ...config import ROOT_DIR
    from ..context.context_offloader import ContextOffloader
    from ..context.runtime_compressor import CompressRuntimeCompressor, NoOpRuntimeCompressor

    if not resolved.compression_active:
        return NoOpRuntimeCompressor()

    offload_dir = os.path.join(
        ROOT_DIR, "data", ".offload", parent_session_id, child_session_id,
    )
    offloader = ContextOffloader(
        offload_dir,
        threshold=resolved.offload_threshold,
        summary_strategy=resolved.offload_summary_strategy,
        summary_chars=resolved.offload_summary_chars,
        provider=parent.provider,
    )
    return CompressRuntimeCompressor(keep_recent=3, offloader=offloader)


def merge_engine_subagent_block(
    engine_cfg: dict | None,
    *,
    flat_token_budget: int | None = None,
) -> dict[str, Any]:
    """规范化 engine_config.subagent，并兼容旧扁平 subagent_token_budget。"""
    engine_cfg = dict(engine_cfg or {})
    nested = normalize_subagent_runtime_dict(engine_cfg.get("subagent"))
    if "token_budget" not in nested:
        legacy = engine_cfg.get("subagent_token_budget", flat_token_budget)
        parsed = _as_optional_int(legacy)
        if parsed is not None:
            nested["token_budget"] = parsed
    return nested

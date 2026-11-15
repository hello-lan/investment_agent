"""Agent 配置工厂 — 从 DB + settings.json 构建 AgentRunConfig。

属于 app 层：依赖 app.db 和 config.py，agent 包不 import 此模块。
"""

from __future__ import annotations

import json

from ..agent.config import (
    AgentRunConfig,
    DEFAULT_SYSTEM_PROMPT,
    PLANNING_MAX_TOKENS_DEFAULT,
    SUBAGENT_WORKSPACE_DIR_DEFAULT,
)
from ..agent.constants import OffloadSummaryStrategy, ProviderType, LoopMode
from ..agent.core.provider import ClaudeProvider, ModelProvider, OpenAICompatProvider
from ..agent.skills.cache import get_cache
from ..config import get_settings
from .storage import SqliteStorage

_storage = SqliteStorage()


async def get_provider(model_id: str | None = None) -> ModelProvider:
    """从数据库 models 表读取配置，创建对应的 ModelProvider 实例。

    复用 SqliteStorage.get_model_config 的查询逻辑，避免重复。
    """
    cfg = await _storage.get_model_config(model_id)

    if not cfg:
        raise ValueError("No model configured. Please add a model in Settings.")

    if cfg["type"] == ProviderType.ANTHROPIC:
        provider = ClaudeProvider(api_key=cfg["api_key"], model=cfg["model"])
    else:
        provider = OpenAICompatProvider(
            api_key=cfg["api_key"],
            model=cfg["model"],
            base_url=cfg["base_url"] or "https://api.openai.com/v1",
        )
    provider.input_price = cfg["input_price"] if cfg["input_price"] is not None else None
    provider.output_price = cfg["output_price"] if cfg["output_price"] is not None else None
    provider.currency = cfg["currency"] or "USD"
    provider.cache_read_price = cfg.get("cache_read_price")
    provider.cache_creation_price = cfg.get("cache_creation_price")

    # 缓存控制：仅当模型配置明确启用 + provider 类型支持时才开启
    if cfg.get("enable_cache", True):
        provider.supports_cache_control = True

    return provider


def _normalize_loop_mode(value, workflow_id: str | None = None) -> str:
    """标准化 loop_mode，兼容旧 workflow=plan_execute 数据。"""
    if value == LoopMode.WORKFLOW and not workflow_id:
        return LoopMode.PLAN_EXECUTE
    try:
        return LoopMode(value)
    except (TypeError, ValueError):
        return LoopMode.DUAL_LOOP


def _resolve_preferring_agent(agent_cfg: dict, global_cfg: dict, key: str, default=None):
    """优先使用 Agent 显式值；仅在缺失或为 None 时回退到全局/默认。"""
    if key in agent_cfg and agent_cfg.get(key) is not None:
        return agent_cfg.get(key)
    if key in global_cfg and global_cfg.get(key) is not None:
        return global_cfg.get(key)
    return default


def _resolve_engine_params(agent_cfg: dict | None) -> dict:
    """合并 agent 级 engine_config 与全局 settings，返回已解析的引擎参数。"""
    settings = get_settings()
    global_cfg = settings.get("engine", {})
    agent_cfg = agent_cfg or {}

    runtime_context_compression_enabled = _resolve_preferring_agent(
        agent_cfg,
        global_cfg,
        "runtime_context_compression_enabled",
        True,
    )
    workflow_id = _resolve_preferring_agent(agent_cfg, global_cfg, "workflow_id")
    context_trim_token_threshold = _resolve_preferring_agent(
        agent_cfg,
        global_cfg,
        "context_trim_token_threshold",
        0,
    )
    if runtime_context_compression_enabled is False:
        context_trim_token_threshold = 0

    return {
        "max_steps": _resolve_preferring_agent(agent_cfg, global_cfg, "max_steps", 30),
        "slow_think_interval": _resolve_preferring_agent(agent_cfg, global_cfg, "slow_think_interval", 3),
        "loop_mode": _normalize_loop_mode(
            _resolve_preferring_agent(agent_cfg, global_cfg, "loop_mode", LoopMode.DUAL_LOOP),
            workflow_id=workflow_id,
        ),
        "workflow_id": workflow_id,
        "token_budget": _resolve_preferring_agent(agent_cfg, global_cfg, "token_budget", 100000),
        "loop_detection_threshold": _resolve_preferring_agent(agent_cfg, global_cfg, "loop_detection_threshold", 3),
        "runtime_context_compression_enabled": runtime_context_compression_enabled,
        "context_trim_token_threshold": context_trim_token_threshold,
        "max_subagent_depth": _resolve_preferring_agent(agent_cfg, global_cfg, "max_subagent_depth", 3),
        "offload_threshold": _resolve_preferring_agent(agent_cfg, global_cfg, "offload_threshold", 800),
        "offload_summary_strategy": _resolve_preferring_agent(
            agent_cfg, global_cfg, "offload_summary_strategy", OffloadSummaryStrategy.TRUNCATE,
        ),
        "offload_summary_chars": _resolve_preferring_agent(agent_cfg, global_cfg, "offload_summary_chars", 200),
        "planning_max_tokens": _resolve_preferring_agent(
            agent_cfg, global_cfg, "planning_max_tokens", PLANNING_MAX_TOKENS_DEFAULT,
        ),
        "subagent_workspace_dir": _resolve_preferring_agent(
            agent_cfg, global_cfg, "subagent_workspace_dir", SUBAGENT_WORKSPACE_DIR_DEFAULT,
        ),
    }


def _resolve_context_config(agent_compress_cfg: dict | None) -> dict:
    """合并 agent 级 compress_config 与全局 settings.context。"""
    settings = get_settings()
    context_cfg = dict(settings.get("context", {}))
    if agent_compress_cfg:
        context_cfg.update(agent_compress_cfg)
    return context_cfg


def _parse_json_field(value, default=None):
    """安全解析 JSON 字段：支持 str/dict/None 输入。"""
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _parse_agent_fields(agent_row: dict | None) -> dict:
    """从 agent DB 行解析所有字段，返回标准化的配置字典。"""
    if not agent_row:
        return {
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "agent_name": None,
            "model_id": None,
            "temperature": None,
            "max_tokens": None,
            "skills": [],
            "tools": [],
            "engine_config": None,
            "compress_config": None,
        }

    return {
        "system_prompt": agent_row["system_prompt"] or DEFAULT_SYSTEM_PROMPT,
        "agent_name": agent_row["name"],
        "model_id": agent_row["model_id"] or None,
        "temperature": agent_row["temperature"] if agent_row["temperature"] is not None else None,
        "max_tokens": agent_row["max_tokens"] if agent_row["max_tokens"] is not None else None,
        "skills": _parse_json_field(agent_row["skills"], []),
        "tools": _parse_json_field(agent_row["tools"], []),
        "engine_config": _parse_json_field(agent_row["engine_config"]),
        "compress_config": _parse_json_field(agent_row["compress_config"]),
    }


async def load_agent_run_config(agent_id: str | None = None) -> AgentRunConfig:
    """加载并合并所有配置源，返回一次 Agent 运行所需的全部配置。

    合并来源：
    1. settings.json (engine + context 全局默认值)
    2. agents 表（system_prompt, model_id, skills, engine_config, compress_config, temperature, max_tokens）
    3. models 表（api_key, model, base_url, 定价）
    4. Skill 正文注入到 system prompt
    """
    # —— 加载 Agent DB 行 ——
    agent_row = None
    if agent_id:
        agent_row = await _storage.get_agent_config(agent_id)

    fields = _parse_agent_fields(agent_row)

    # —— 配置 Skill body 缓存 TTL ——
    ttl = get_settings().get("engine", {}).get("skill_body_ttl", 600)
    get_cache().set_ttl(ttl)

    # —— Provider ——
    provider = await get_provider(fields["model_id"])

    # —— Context config ——
    context_cfg = _resolve_context_config(fields["compress_config"])

    # —— Engine params ——
    engine_params = _resolve_engine_params(fields["engine_config"])

    # —— Context config ——

    return AgentRunConfig(
        provider=provider,
        model_name=provider.model,
        system_prompt=fields["system_prompt"],
        agent_id=agent_id,
        agent_name=fields["agent_name"],
        temperature=fields["temperature"],
        max_tokens=fields["max_tokens"],
        max_steps=engine_params["max_steps"],
        slow_think_interval=engine_params["slow_think_interval"],
        loop_mode=engine_params["loop_mode"],
        token_budget=engine_params["token_budget"],
        loop_detection_threshold=engine_params["loop_detection_threshold"],
        context_trim_token_threshold=engine_params["context_trim_token_threshold"],
        runtime_context_compression_enabled=engine_params["runtime_context_compression_enabled"],
        tools=fields["tools"],
        skills=fields["skills"],
        context=context_cfg,
        max_subagent_depth=engine_params["max_subagent_depth"],
        offload_threshold=engine_params["offload_threshold"],
        offload_summary_strategy=engine_params["offload_summary_strategy"],
        offload_summary_chars=engine_params["offload_summary_chars"],
        planning_max_tokens=engine_params["planning_max_tokens"],
        subagent_workspace_dir=engine_params["subagent_workspace_dir"],
        workflow_id=engine_params["workflow_id"],
        input_price=provider.input_price,
        output_price=provider.output_price,
        currency=provider.currency,
    )

"""Agent 配置工厂 — 从 DB + settings.json 构建 AgentRunConfig。

属于 app 层：依赖 app.db 和 config.py，agent 包不 import 此模块。
"""

from __future__ import annotations

import json

from ..agent.config import AgentRunConfig, DEFAULT_SYSTEM_PROMPT
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

    if cfg["type"] == "anthropic":
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
    return provider


def _resolve_engine_params(agent_cfg: dict | None) -> dict:
    """合并 agent 级 engine_config 与全局 settings，返回已解析的引擎参数。"""
    settings = get_settings()
    global_cfg = settings.get("engine", {})
    agent_cfg = agent_cfg or {}
    return {
        "max_steps": agent_cfg.get("max_steps") or global_cfg.get("max_steps", 30),
        "slow_think_interval": agent_cfg.get("slow_think_interval") or global_cfg.get("slow_think_interval", 3),
        "token_budget": agent_cfg.get("token_budget") or global_cfg.get("token_budget", 100000),
        "loop_detection_threshold": agent_cfg.get("loop_detection_threshold") or global_cfg.get("loop_detection_threshold", 3),
        "context_trim_interval": agent_cfg.get("context_trim_interval") or global_cfg.get("context_trim_interval", 0),
        "runtime_trim_strategy": agent_cfg.get("runtime_trim_strategy") or global_cfg.get("runtime_trim_strategy", "compress"),
        "tool_trim_limits": agent_cfg.get("tool_trim_limits") or global_cfg.get("tool_trim_limits", {}),
        "max_subagent_depth": agent_cfg.get("max_subagent_depth") or global_cfg.get("max_subagent_depth", 3),
        "offload_threshold": agent_cfg.get("offload_threshold")
                             or global_cfg.get("offload_threshold", 800),
        "offload_summary_strategy": agent_cfg.get("offload_summary_strategy")
                                    or global_cfg.get("offload_summary_strategy", "truncate"),
        "offload_summary_chars": agent_cfg.get("offload_summary_chars")
                                 or global_cfg.get("offload_summary_chars", 200),
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

    # —— Engine params ——
    engine_params = _resolve_engine_params(fields["engine_config"])

    # —— Context config ——
    context_cfg = _resolve_context_config(fields["compress_config"])

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
        token_budget=engine_params["token_budget"],
        loop_detection_threshold=engine_params["loop_detection_threshold"],
        context_trim_interval=engine_params["context_trim_interval"],
        runtime_trim_strategy=engine_params["runtime_trim_strategy"],
        tools=fields["tools"],
        skills=fields["skills"],
        tool_trim_limits=engine_params["tool_trim_limits"],
        context=context_cfg,
        max_subagent_depth=engine_params["max_subagent_depth"],
        offload_threshold=engine_params["offload_threshold"],
        offload_summary_strategy=engine_params["offload_summary_strategy"],
        offload_summary_chars=engine_params["offload_summary_chars"],
        input_price=provider.input_price,
        output_price=provider.output_price,
        currency=provider.currency,
    )

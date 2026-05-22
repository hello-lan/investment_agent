"""Agent 配置工厂 — 从 DB + settings.json 构建 AgentRunConfig。

属于 app 层：依赖 app.db 和 config.py，agent 包不 import 此模块。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..agent.config import AgentRunConfig
from ..agent.core.models import ClaudeProvider, ModelProvider, OpenAICompatProvider
from ..agent.skills.cache import get_cache
from ..agent.skills.loader import get_skill
from ..config import PROJECT_ROOT, get_settings
from .db import get_db


async def get_provider(model_id: str | None = None) -> ModelProvider:
    """从数据库 models 表读取配置，创建对应的 ModelProvider 实例"""
    async with get_db() as db:
        if model_id:
            row = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        else:
            row = await db.execute("SELECT * FROM models WHERE is_default = 1 LIMIT 1")
        cfg = await row.fetchone()

        if not cfg:
            row = await db.execute("SELECT * FROM models LIMIT 1")
            cfg = await row.fetchone()

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
    provider._input_price = cfg["input_price"] if cfg["input_price"] is not None else None
    provider._output_price = cfg["output_price"] if cfg["output_price"] is not None else None
    provider._currency = cfg["currency"] or "USD"
    return provider


DEFAULT_SYSTEM_PROMPT = """你是一位专业的A股投研分析师。
你可以调用工具获取股票行情、财务报表、估值指标等数据，帮助用户进行基本面分析。
分析时请做到：数据驱动、逻辑清晰、结论明确。
最终输出请使用 Markdown 格式。

## 项目路径

PROJECT_ROOT = {PROJECT_ROOT}

## 文件输出规范
- PDF 财报文件保存到 {PROJECT_ROOT}/data/reports/pdf/{股票代码}/
- Markdown 分析报告保存到 {PROJECT_ROOT}/data/reports/
- 图表保存到 {PROJECT_ROOT}/data/reports/charts/
- 临时文件放到 {PROJECT_ROOT}/data/tmp/
- 调用 download-a-share-reports 技能下载财报时，必须传递 --save-dir {PROJECT_ROOT}/data/reports/pdf/"""


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
        "tool_trim_limits": agent_cfg.get("tool_trim_limits") or global_cfg.get("tool_trim_limits", {}),
    }


def _resolve_context_config(agent_compress_cfg: dict | None) -> dict:
    """合并 agent 级 compress_config 与全局 settings.context。"""
    settings = get_settings()
    context_cfg = dict(settings.get("context", {}))
    if agent_compress_cfg:
        context_cfg.update(agent_compress_cfg)
    return context_cfg


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
        async with get_db() as db:
            row = await db.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,),
            )
            agent_row = await row.fetchone()

    # —— System prompt ——
    system_prompt = DEFAULT_SYSTEM_PROMPT.replace("{PROJECT_ROOT}", str(PROJECT_ROOT))
    agent_name = None
    model_id = None
    enabled_skill_names: list[str] = []
    agent_engine_config: dict | None = None
    agent_compress_config: dict | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    if agent_row:
        agent_name = agent_row["name"]
        if agent_row["system_prompt"]:
            system_prompt = agent_row["system_prompt"]
        model_id = agent_row["model_id"] or None
        temperature = agent_row["temperature"] if agent_row["temperature"] is not None else None
        max_tokens = agent_row["max_tokens"] if agent_row["max_tokens"] is not None else None
        try:
            enabled_skill_names = json.loads(agent_row["skills"] or "[]")
        except Exception:
            enabled_skill_names = []
        try:
            raw_engine = agent_row["engine_config"]
            if isinstance(raw_engine, str) and raw_engine.strip():
                agent_engine_config = json.loads(raw_engine)
            elif isinstance(raw_engine, dict):
                agent_engine_config = raw_engine
        except Exception:
            agent_engine_config = None
        try:
            raw_compress = agent_row["compress_config"]
            if isinstance(raw_compress, str) and raw_compress.strip():
                agent_compress_config = json.loads(raw_compress)
            elif isinstance(raw_compress, dict):
                agent_compress_config = raw_compress
        except Exception:
            agent_compress_config = None

    # —— 注入 Skill meta 到 system prompt（仅名称+描述，不含 body） ——
    if enabled_skill_names:
        skill_lines = []
        for name in enabled_skill_names:
            skill = get_skill(name)
            if skill:
                prefix = "[orch] " if skill.skill_type == "orch" else ""
                deps_hint = ""
                if skill.depends_on:
                    deps_hint = f"（含 {len(skill.depends_on)} 个子流程）"
                skill_lines.append(
                    f"- {prefix}**{skill.name}**: {skill.description}{deps_hint}"
                )
        if skill_lines:
            system_prompt += (
                "\n\n---\n\n# 可用技能\n\n"
                + "\n".join(skill_lines)
                + "\n\n> 使用 Skill 工具加载技能完整说明后再执行。"
            )

    # —— 配置 Skill body 缓存 TTL ——
    ttl = get_settings().get("engine", {}).get("skill_body_ttl", 600)
    get_cache().set_ttl(ttl)

    # —— Provider ——
    provider = await get_provider(model_id)
    model_name = provider.model

    # —— Engine params ——
    engine_params = _resolve_engine_params(agent_engine_config)

    # —— Context config ——
    context_cfg = _resolve_context_config(agent_compress_config)

    return AgentRunConfig(
        provider=provider,
        model_name=model_name,
        system_prompt=system_prompt,
        agent_id=agent_id,
        agent_name=agent_name,
        temperature=temperature,
        max_tokens=max_tokens,
        max_steps=engine_params["max_steps"],
        slow_think_interval=engine_params["slow_think_interval"],
        token_budget=engine_params["token_budget"],
        loop_detection_threshold=engine_params["loop_detection_threshold"],
        context_trim_interval=engine_params["context_trim_interval"],
        tool_trim_limits=engine_params["tool_trim_limits"],
        context=context_cfg,
        input_price=getattr(provider, "_input_price", None),
        output_price=getattr(provider, "_output_price", None),
        currency=getattr(provider, "_currency", "USD"),
    )

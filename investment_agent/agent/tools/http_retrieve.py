"""HTTP 检索模板。

每份已保存的实例才是一个工具：显示名给人看，调用名给模型用。
请求参数表里，来源为 llm 的字段进入工具 schema，来源为 fixed 的字段调用时并进请求体。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import httpx

from .base import BaseTool
from .result_formatter import format_tool_result

_log = logging.getLogger(__name__)

TEMPLATE_ID = "http_retrieve"
LEGACY_TEMPLATE_IDS = {"rag_retrieve"}
TEMPLATE_LABEL = "HTTP 检索"
TEMPLATE_DESCRIPTION = "调用外部检索服务，只返回命中的原文片段。"

DEFAULT_PATH = "/retrieve"
DEFAULT_TIMEOUT = 90

PARAM_TYPES = ("string", "integer", "number", "boolean", "array")

DEFAULT_PARAMS: list[dict[str, Any]] = [
    {
        "key": "",
        "source": "llm",
        "type": "string",
        "required": True,
        "description": "",
        "value": "",
    },
]

GetInstance = Callable[[str], Awaitable[dict | None]]
ListInstances = Callable[[], Awaitable[list[dict]]]

_get_instance: GetInstance | None = None
_list_instances: ListInstances | None = None
_cache: dict[str, dict] = {}


def set_instance_loaders(get_instance: GetInstance, list_instances: ListInstances) -> None:
    """由应用启动时注入读取函数，避免工具模块依赖 app.db。"""
    global _get_instance, _list_instances
    _get_instance = get_instance
    _list_instances = list_instances


def cached_instances() -> list[dict]:
    return list(_cache.values())


async def refresh_instance_cache() -> None:
    """用当前已保存的实例替换进程内缓存，供引擎注册工具 schema。"""
    global _cache
    if _list_instances is None:
        return
    rows = await _list_instances()
    _cache = {row["tool_name"]: row for row in rows if row.get("tool_name")}


def describe_instance(instance: dict) -> str:
    custom = (instance.get("description") or "").strip()
    if custom:
        return custom
    label = instance.get("display_name") or instance.get("tool_name") or "检索"
    return f"从「{label}」检索原文片段，只返回命中材料。"


def default_template() -> dict:
    return {
        "id": TEMPLATE_ID,
        "label": TEMPLATE_LABEL,
        "description": TEMPLATE_DESCRIPTION,
        "defaults": {
            "path": DEFAULT_PATH,
            "timeout_seconds": DEFAULT_TIMEOUT,
            "params": [dict(item) for item in DEFAULT_PARAMS],
        },
    }


def build_schema(instance: dict) -> dict:
    properties: dict[str, dict] = {}
    required: list[str] = []
    for param in instance.get("params") or []:
        if param.get("source") != "llm":
            continue
        key = param.get("key") or ""
        if not key:
            continue
        prop: dict[str, Any] = {
            "type": param.get("type") or "string",
            "description": (param.get("description") or key).strip(),
        }
        if prop["type"] == "array":
            prop["items"] = {"type": "string"}
        properties[key] = prop
        if param.get("required"):
            required.append(key)
    return {
        "name": instance["tool_name"],
        "description": describe_instance(instance),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def prompt_section(instances: list[dict]) -> str:
    if not instances:
        return ""
    lines = [
        "\n\n## 检索工具",
        "查年报原文、互动问答、调研、研报、新闻或投资通识时，调用下列检索工具。",
        "回答必须依据返回片段。材料不够就说明缺什么，并用片段中的来源标注依据。",
    ]
    for inst in instances:
        lines.append(f"- {inst['tool_name']}（{inst['display_name']}）：{describe_instance(inst)}")
        llm_keys = [p.get("key") for p in inst.get("params") or [] if p.get("source") == "llm"]
        hinted = [key for key in ("stock_code", "company") if key in llm_keys]
        if hinted:
            joined = " 或 ".join(hinted)
            lines.append(f"  用户点名公司时，必须传入 {joined}。")
    return "\n".join(lines)


def _coerce_array(value: Any) -> list | None:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        raise ValueError(f"无法把 {value!r} 转成数组")
    text = value.strip()
    if not text:
        return None
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError(f"无法把 {value!r} 转成数组")
        return [str(item) for item in parsed]
    return [item.strip() for item in text.split(",") if item.strip()]


def _coerce(value: Any, typ: str) -> Any:
    if value is None:
        return None
    if typ == "array":
        return _coerce_array(value)
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if typ == "string":
        return str(value)
    if typ == "integer":
        return int(value)
    if typ == "number":
        return float(value)
    if typ == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes"):
            return True
        if text in ("false", "0", "no"):
            return False
        raise ValueError(f"无法把 {value!r} 转成布尔值")
    return value


def build_request_body(instance: dict, arguments: dict) -> tuple[dict | None, str | None]:
    """合并模型参数和固定值。固定值覆盖同名的模型参数。"""
    body: dict[str, Any] = {}
    params = list(instance.get("params") or [])
    for param in params:
        if param.get("source") != "llm":
            continue
        key = param.get("key")
        if not key or key not in arguments:
            continue
        try:
            value = _coerce(arguments.get(key), param.get("type") or "string")
        except (TypeError, ValueError) as exc:
            return None, f"参数 {key} 无法转换：{exc}"
        if value is None:
            continue
        body[key] = value
    for param in params:
        if param.get("source") != "fixed":
            continue
        key = param.get("key")
        if not key:
            continue
        try:
            value = _coerce(param.get("value"), param.get("type") or "string")
        except (TypeError, ValueError) as exc:
            return None, f"固定参数 {key} 无法转换：{exc}"
        if value is None:
            continue
        body[key] = value
    return body, None


def request_url(instance: dict) -> str:
    base = (instance.get("base_url") or "").rstrip("/")
    path = (instance.get("path") or DEFAULT_PATH).strip() or DEFAULT_PATH
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def format_hits(tool_name: str, payload: dict) -> str:
    hits = payload.get("hits")
    if not isinstance(hits, list):
        return format_tool_result(tool_name, "检索服务没有返回 hits。", mode=payload.get("mode"))
    blocks: list[str] = []
    for index, hit in enumerate(hits, start=1):
        if not isinstance(hit, dict):
            continue
        rank = hit.get("rank") or index
        year = hit.get("year")
        year_text = "-" if year in (None, "") else str(year)
        chunk_idx = hit.get("chunk_idx")
        chunk_text = "-" if chunk_idx is None else str(chunk_idx)
        meta = " ".join([
            f"类型={hit.get('doc_type') or '-'}",
            f"公司={hit.get('company') or '-'}",
            f"代码={hit.get('stock_code') or '-'}",
            f"年份={year_text}",
            f"报告期={hit.get('period') or '-'}",
            f"来源={hit.get('source_name') or hit.get('title') or '-'}",
            f"chunk={chunk_text}",
        ])
        blocks.append(f"[{rank}] {meta}\n{hit.get('chunk_text') or ''}")
    body = "\n\n".join(blocks) if blocks else "没有命中。"
    return format_tool_result(tool_name, body, mode=payload.get("mode"), hits=len(blocks))


class HttpRetrieveTool(BaseTool):
    """一份检索实例对应一个工具。调用时重新读取配置。"""

    risk_level = 0
    trim_max_chars = 12000

    def __init__(self, snapshot: dict):
        self.name = snapshot["tool_name"]
        self.description = describe_instance(snapshot)
        self._snapshot = snapshot

    @property
    def schema(self) -> dict:
        return build_schema(self._snapshot)

    async def run(self, **kwargs) -> str:
        current = self._snapshot
        if _get_instance is not None:
            loaded = await _get_instance(self.name)
            if not loaded:
                return "工具配置不存在"
            current = loaded
        body, error = build_request_body(current, kwargs)
        if error:
            return error
        missing = [
            param.get("key")
            for param in current.get("params") or []
            if param.get("source") == "llm" and param.get("required") and param.get("key") not in (body or {})
        ]
        if missing:
            return "缺少参数: " + ", ".join(missing)
        url = request_url(current)
        if not url.startswith("http://") and not url.startswith("https://"):
            return "检索地址未配置。"
        timeout = float(current.get("timeout_seconds") or DEFAULT_TIMEOUT)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(url, json=body or {})
        except httpx.TimeoutException:
            return "检索超时。"
        except httpx.HTTPError as exc:
            _log.warning("检索连接失败 %s: %s", url, exc)
            return f"无法连接检索服务: {exc}"
        if response.status_code >= 400:
            detail = response.text[:500]
            return f"检索服务返回 {response.status_code}: {detail}"
        try:
            payload = response.json()
        except ValueError:
            return "检索结果无法解析。"
        if not isinstance(payload, dict):
            return "检索结果无法识别。"
        return format_hits(self.name, payload)


def mount_retrieve_tools(engine, names: set[str]) -> list[dict]:
    """把缓存中、且调用名被选中的实例注册到引擎，并写入系统提示。"""
    selected = set(names or [])
    mounted: list[dict] = []
    for instance in cached_instances():
        if instance.get("tool_name") not in selected:
            continue
        if instance.get("template") not in (None, "", TEMPLATE_ID, *LEGACY_TEMPLATE_IDS):
            continue
        tool = HttpRetrieveTool(instance)
        engine.register_tool(tool.schema, tool.run)
        mounted.append(instance)
    if mounted:
        engine._system_prompt += prompt_section(mounted)
        engine._prompt_builder = None
    return mounted

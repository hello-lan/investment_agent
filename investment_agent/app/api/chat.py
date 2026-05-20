"""聊天 API — HTTP 请求解析 + SSE 流式响应。

Agent 逻辑全部委托给 AgentRunner，本层只处理 HTTP 层面的事务。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...agent import AgentRunner
from ..config_factory import load_agent_run_config
from ..observability.hooks_impl import ObservabilityHooks
from ..storage import SqliteStorage
from ..utils.file_parser import (
    ALLOWED_EXTS,
    MAX_FILE_TEXT_CHARS,
    build_user_message,
    extract_file_text,
    normalize_name,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    agent_id: str | None = None


# ── 请求解析（HTTP 层专属）────────────────────────────────────────────


async def _parse_request_payload(
    request: Request,
) -> tuple[str | None, str, str | None, str | None, str | None]:
    """解析请求体：支持 JSON 和 multipart/form-data（带文件上传）。"""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        body = ChatRequest.model_validate(await request.json())
        return body.session_id, body.message, body.agent_id, None, None

    if "multipart/form-data" in content_type:
        form = await request.form()
        session_id = (form.get("session_id") or "").strip() or None
        message = str(form.get("message") or "").strip()
        agent_id = (form.get("agent_id") or "").strip() or None
        upload = form.get("file")

        filename_attr = getattr(upload, "filename", None)
        if not upload or not filename_attr:
            return session_id, message, agent_id, None, None

        filename = normalize_name(str(filename_attr))
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or 'unknown'}")

        content = await upload.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件过大，最大支持 10MB")

        try:
            file_text = extract_file_text(filename, ext, content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

        if not file_text.strip():
            raise HTTPException(status_code=400, detail="文件内容为空或不可提取")

        return session_id, message, agent_id, filename, file_text

    raise HTTPException(status_code=415, detail="仅支持 application/json 或 multipart/form-data")


# ── 端点 ─────────────────────────────────────────────────────────────


@router.post("")
async def start_chat(request: Request):
    """发起对话：解析请求，加载配置，委托 AgentRunner 创建引擎。"""
    session_id, message, agent_id, filename, file_text = await _parse_request_payload(request)
    final_message = build_user_message(message, filename, file_text)
    if not final_message.strip():
        raise HTTPException(status_code=400, detail="消息和文件不能同时为空")

    config = await load_agent_run_config(agent_id)
    runner = AgentRunner(storage=SqliteStorage())
    task_id, session_id = await runner.start(
        session_id=session_id or str(uuid.uuid4()),
        config=config,
        message=final_message,
    )
    return {"task_id": task_id, "session_id": session_id}


@router.get("/{task_id}/stream")
async def stream_chat(task_id: str):
    """SSE 流式端点：委托 AgentRunner 执行引擎，通过 hooks 记录可观测性。"""
    runner = AgentRunner(storage=SqliteStorage())
    hooks = ObservabilityHooks(task_id=task_id)

    async def event_stream():
        try:
            async for event in runner.run(task_id, hooks=hooks):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await runner.save_response()
        finally:
            runner.cleanup(task_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/interrupt")
async def interrupt_chat(task_id: str):
    ok = AgentRunner.interrupt(task_id)
    return {"success": ok}

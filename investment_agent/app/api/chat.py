"""聊天 API — HTTP 请求解析 + SSE 流式响应。

Agent 逻辑全部委托给 AgentRunner，本层只处理 HTTP 层面的事务。
任务执行通过 TaskManager 在后台独立运行，与 SSE 连接解耦。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...agent import AgentRunner
from ...config import ROOT_DIR
from ..config_factory import load_agent_run_config
from ..storage import SqliteStorage
from ..task_manager import task_manager
from ..utils.file_parser import (
    ALLOWED_EXTS,
    build_user_message,
    normalize_name,
    timestamped_filename,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])

def _normalize_context_mode(value: str | None) -> str | None:
    if not value:
        return None
    mode = str(value).strip().lower()
    return mode if mode in ("chat", "full") else None


def _normalize_collaboration_mode(value: str | None) -> str | None:
    if not value:
        return None
    mode = str(value).strip().lower()
    return mode if mode in ("agent", "plan") else None


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOADS_DIR = ROOT_DIR / "data" / "uploads"


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    agent_id: str | None = None
    model_id: str | None = None
    context_mode: str | None = None
    collaboration_mode: str | None = None


class RetryRequest(BaseModel):
    session_id: str
    model_id: str | None = None


class EditRequest(BaseModel):
    session_id: str
    message_id: str
    message: str
    model_id: str | None = None


# ── 请求解析（HTTP 层专属）────────────────────────────────────────────


async def _parse_request_payload(
    request: Request,
) -> tuple[str | None, str, str | None, str | None, str | None, str | None, str | None]:
    """解析请求体：支持 JSON 和 multipart/form-data（带文件上传）。

    返回: session_id, message, agent_id, uploaded_path, model_id, context_mode, collaboration_mode
    uploaded_path 为相对项目根的路径（正斜杠），如 data/uploads/xxx.pdf。
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        body = ChatRequest.model_validate(await request.json())
        model_id = (body.model_id or "").strip() or None
        return (
            body.session_id, body.message, body.agent_id, None, model_id,
            _normalize_context_mode(body.context_mode),
            _normalize_collaboration_mode(body.collaboration_mode),
        )

    if "multipart/form-data" in content_type:
        form = await request.form()
        session_id = (form.get("session_id") or "").strip() or None
        message = str(form.get("message") or "").strip()
        agent_id = (form.get("agent_id") or "").strip() or None
        model_id = (form.get("model_id") or "").strip() or None
        context_mode = _normalize_context_mode(str(form.get("context_mode") or ""))
        collaboration_mode = _normalize_collaboration_mode(str(form.get("collaboration_mode") or ""))
        upload = form.get("file")

        filename_attr = getattr(upload, "filename", None)
        if not upload or not filename_attr:
            return session_id, message, agent_id, None, model_id, context_mode, collaboration_mode

        filename = normalize_name(str(filename_attr))
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or 'unknown'}")

        content = await upload.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="文件过大，最大支持 100MB")

        saved_name = timestamped_filename(filename)
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOADS_DIR / saved_name
        dest.write_bytes(content)

        uploaded_path = f"data/uploads/{saved_name}"
        return (
            session_id, message, agent_id, uploaded_path, model_id,
            context_mode, collaboration_mode,
        )

    raise HTTPException(status_code=415, detail="仅支持 application/json 或 multipart/form-data")


async def _start_background_task(
    runner: AgentRunner,
    task_id: str,
    config,
    session_id: str,
    *,
    uploaded_path: str | None = None,
) -> dict[str, str]:
    """统一注册后台任务并返回标准响应体。"""
    engine = AgentRunner.get_engine(task_id)
    await task_manager.start_task(task_id, engine, runner, config, session_id)
    result: dict[str, str] = {"task_id": task_id, "session_id": session_id}
    message_id = runner.turn_user_message_id()
    if message_id:
        result["message_id"] = message_id
    if uploaded_path:
        result["uploaded_path"] = uploaded_path
    return result


# ── 端点 ─────────────────────────────────────────────────────────────


@router.post("")
async def start_chat(request: Request):
    """发起对话：解析请求，加载配置，创建引擎并在后台启动任务。"""
    (
        session_id, message, agent_id, uploaded_path, model_id,
        context_mode, collaboration_mode,
    ) = await _parse_request_payload(request)
    final_message = build_user_message(message, uploaded_path)
    if not final_message.strip():
        raise HTTPException(status_code=400, detail="消息和文件不能同时为空")

    config = await load_agent_run_config(agent_id, model_id=model_id)
    runner = AgentRunner(storage=SqliteStorage())
    task_id, session_id = await runner.start(
        session_id=session_id or str(uuid.uuid4()),
        config=config,
        message=final_message,
        context_mode=context_mode,
        collaboration_mode=collaboration_mode,
    )
    return await _start_background_task(
        runner, task_id, config, session_id, uploaded_path=uploaded_path
    )


@router.get("/{task_id}/stream")
async def stream_chat(task_id: str):
    """SSE 流式端点：订阅 TaskManager 事件，支持断开重连回放。"""
    async def event_stream():
        async for event in task_manager.stream_events(task_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/interrupt")
async def interrupt_chat(task_id: str):
    ok = AgentRunner.interrupt(task_id)
    return {"success": ok}


@router.post("/retry")
async def retry_chat(body: RetryRequest):
    """重试对话：复用同一 session，重新创建引擎执行。"""
    session_id = body.session_id
    storage = SqliteStorage()

    # 检查是否有正在运行的任务
    running_task = await storage.get_session_running_task(session_id)
    if running_task:
        raise HTTPException(status_code=409, detail="该会话有正在运行的任务，无法重试")

    # 加载会话的 agent 配置（可带会话级 model 覆盖）
    agent_id = await storage.get_session_agent_id(session_id)
    model_id = (body.model_id or "").strip() or None
    config = await load_agent_run_config(agent_id, model_id=model_id)

    runner = AgentRunner(storage=storage)
    task_id, session_id = await runner.setup(session_id, config)
    return await _start_background_task(runner, task_id, config, session_id)


@router.post("/edit")
async def edit_chat(body: EditRequest):
    """编辑用户消息并时间倒流：截断后续记录后按新内容重跑。"""
    session_id = body.session_id
    message_id = (body.message_id or "").strip()
    message = (body.message or "").strip()
    if not message_id:
        raise HTTPException(status_code=400, detail="message_id 不能为空")
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    storage = SqliteStorage()
    running_task = await storage.get_session_running_task(session_id)
    if running_task:
        raise HTTPException(status_code=409, detail="该会话有正在运行的任务，无法编辑")

    try:
        await storage.rewind_and_update_user_message(session_id, message_id, message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    agent_id = await storage.get_session_agent_id(session_id)
    model_id = (body.model_id or "").strip() or None
    config = await load_agent_run_config(agent_id, model_id=model_id)

    runner = AgentRunner(storage=storage)
    task_id, session_id = await runner.setup(session_id, config)
    return await _start_background_task(runner, task_id, config, session_id)


@router.get("/{task_id}/status")
async def task_status(task_id: str):
    """查询任务运行状态。"""
    running = task_manager.is_running(task_id)
    session_id = task_manager.get_session_id(task_id)
    return {
        "running": running,
        "done": not running,
        "session_id": session_id,
    }

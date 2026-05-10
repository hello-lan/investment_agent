import json
import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.session import create_engine, get_engine, interrupt_engine, remove_engine
from db import get_db
from tools.registry import get_schemas, get_tool

router = APIRouter(prefix="/api/chat", tags=["chat"])

DEFAULT_SYSTEM_PROMPT = """你是一位专业的A股投研分析师。
你可以调用工具获取股票行情、财务报表、估值指标等数据，帮助用户进行基本面分析。
分析时请做到：数据驱动、逻辑清晰、结论明确。
最终输出请使用 Markdown 格式。"""


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    agent_id: str | None = None


@router.post("")
async def start_chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    async with get_db() as db:
        row = await db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        exists = await row.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO sessions (id, agent_id, title, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                (session_id, req.agent_id, req.message[:50], now),
            )
            await db.commit()

        msg_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (msg_id, session_id, req.message, now),
        )
        await db.commit()

    system_prompt = DEFAULT_SYSTEM_PROMPT
    model_id = None
    if req.agent_id:
        async with get_db() as db:
            row = await db.execute(
                "SELECT system_prompt, model_id FROM agents WHERE id = ?", (req.agent_id,)
            )
            agent = await row.fetchone()
            if agent:
                if agent["system_prompt"]:
                    system_prompt = agent["system_prompt"]
                if agent["model_id"]:
                    model_id = agent["model_id"]

    engine = await create_engine(session_id=session_id, system_prompt=system_prompt, provider_name=model_id)

    for tool in get_schemas():
        t = get_tool(tool["name"])
        if t:
            engine.register_tool(tool, t.run)

    return {"task_id": engine.task_id, "session_id": session_id}


@router.get("/{task_id}/stream")
async def stream_chat(task_id: str):
    engine = get_engine(task_id)
    if not engine:
        async def not_found():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Task not found'})}\n\n"
        return StreamingResponse(not_found(), media_type="text/event-stream")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
            (engine.session_id,),
        )
        rows = await cursor.fetchall()

    messages = []
    for r in rows:
        if r["role"] in ("user", "assistant"):
            messages.append({"role": r["role"], "content": r["content"] or ""})

    async def event_stream():
        assistant_content = ""
        try:
            async for event in engine.run(messages):
                if event["type"] == "text_delta":
                    assistant_content += event["content"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if assistant_content:
                now = datetime.utcnow().isoformat()
                async with get_db() as db2:
                    await db2.execute(
                        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                        (str(uuid.uuid4()), engine.session_id, assistant_content, now),
                    )
                    await db2.commit()
        finally:
            remove_engine(task_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/interrupt")
async def interrupt_chat(task_id: str):
    ok = interrupt_engine(task_id)
    return {"success": ok}

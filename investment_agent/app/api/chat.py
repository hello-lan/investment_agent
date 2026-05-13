import json
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pdfplumber
import xlrd
from docx import Document
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from pydantic import BaseModel

from ...agent.context.compressor import compress_messages
from ...agent.core.session import create_engine, get_engine, interrupt_engine, remove_engine
from ...agent.skills.loader import get_skill
from ...agent.tools.registry import get_schemas, get_tool
from ...config import get_settings, PROJECT_ROOT
from ..db import get_db
from ..observability.cost_tracker import log_cost
from ..observability.trace import log_trace

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 默认系统提示词，当 Agent 未自定义时使用
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


class ChatRequest(BaseModel):
    session_id: str | None = None  # 为空则创建新会话
    message: str
    agent_id: str | None = None   # 为空则使用默认 Agent


# 文件上传限制
ALLOWED_EXTS = {".txt", ".md", ".pdf", ".xlsx", ".xls", ".docx", ".doc"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
MAX_FILE_TEXT_CHARS = 50000  # 提取文本上限


def _normalize_name(name: str | None) -> str:
    raw = (name or "uploaded_file").strip()
    safe = re.sub(r"[^\w\-.一-鿿]", "_", raw)
    return safe[:120] or "uploaded_file"


def _clip_text(text: str, max_chars: int = MAX_FILE_TEXT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[文件内容已截断]"


def _extract_pdf_text(content: bytes) -> str:
    parts: list[str] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(f"## Page {i}\n{txt.strip()}")
    return "\n\n".join(parts)


def _extract_xlsx_text(content: bytes) -> str:
    wb = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
    sections: list[str] = []
    for ws in wb.worksheets:
        rows: list[str] = []
        for row in ws.iter_rows(values_only=True):
            values = ["" if v is None else str(v) for v in row]
            line = "\t".join(values).strip()
            if line:
                rows.append(line)
        if rows:
            sections.append(f"## Sheet: {ws.title}\n" + "\n".join(rows))
    return "\n\n".join(sections)


def _extract_xls_text(content: bytes) -> str:
    wb = xlrd.open_workbook(file_contents=content)
    sections: list[str] = []
    for sheet in wb.sheets():
        rows: list[str] = []
        for r in range(sheet.nrows):
            values = [str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            line = "\t".join(values).strip()
            if line:
                rows.append(line)
        if rows:
            sections.append(f"## Sheet: {sheet.name}\n" + "\n".join(rows))
    return "\n\n".join(sections)


def _extract_docx_text(content: bytes) -> str:
    doc = Document(BytesIO(content))
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n".join(parts)


def _extract_doc_text(content: bytes) -> str:
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法解析 .doc 文件内容")


def _extract_file_text(filename: str, ext: str, content: bytes) -> str:
    if ext in {".txt", ".md"}:
        for enc in ("utf-8", "gb18030", "latin-1"):
            try:
                return content.decode(enc)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"文件 {filename} 编码无法识别")
    if ext == ".pdf":
        return _extract_pdf_text(content)
    if ext == ".xlsx":
        return _extract_xlsx_text(content)
    if ext == ".xls":
        return _extract_xls_text(content)
    if ext == ".docx":
        return _extract_docx_text(content)
    if ext == ".doc":
        return _extract_doc_text(content)
    raise ValueError(f"不支持的文件类型: {ext}")


def _build_user_message(message: str, filename: str | None, file_text: str | None) -> str:
    text = (message or "").strip()
    if not filename or not file_text:
        return text
    clipped = _clip_text(file_text.strip())
    file_block = f"[用户上传文件]\n文件名: {filename}\n\n{clipped}\n[/用户上传文件]"
    return file_block if not text else f"{file_block}\n\n用户问题：{text}"


async def _parse_request_payload(request: Request) -> tuple[str | None, str, str | None, str | None, str | None]:
    """解析请求体：支持 JSON 和 multipart/form-data（带文件上传）两种格式"""
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

        filename = _normalize_name(str(filename_attr))
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or 'unknown'}")

        content = await upload.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="文件过大，最大支持 10MB")

        try:
            file_text = _extract_file_text(filename, ext, content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

        if not file_text.strip():
            raise HTTPException(status_code=400, detail="文件内容为空或不可提取")

        return session_id, message, agent_id, filename, file_text

    raise HTTPException(status_code=415, detail="仅支持 application/json 或 multipart/form-data")


@router.post("")
async def start_chat(request: Request):
    """发起对话：创建/续接会话，加载 Agent 配置，注册工具，返回 task_id"""
    # —— 第1步：解析请求 ——
    session_id, message, agent_id, filename, file_text = await _parse_request_payload(request)
    final_message = _build_user_message(message, filename, file_text)
    if not final_message.strip():
        raise HTTPException(status_code=400, detail="消息和文件不能同时为空")

    session_id = session_id or str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # —— 第2步：创建或复用会话 ——
    async with get_db() as db:
        row = await db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        exists = await row.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO sessions (id, agent_id, title, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                (session_id, agent_id, final_message[:50], now),
            )
            await db.commit()

        msg_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (msg_id, session_id, final_message, now),
        )
        await db.commit()

    # —— 第3步：加载 Agent 配置（系统提示词、模型、Skills）——
    system_prompt = DEFAULT_SYSTEM_PROMPT
    model_id = None
    enabled_skill_names: list[str] = []
    if agent_id:
        async with get_db() as db:
            row = await db.execute(
                "SELECT system_prompt, model_id, skills FROM agents WHERE id = ?", (agent_id,)
            )
            agent = await row.fetchone()
            if agent:
                if agent["system_prompt"]:
                    system_prompt = agent["system_prompt"]
                if agent["model_id"]:
                    model_id = agent["model_id"]
                try:
                    enabled_skill_names = json.loads(agent["skills"] or "[]")
                except Exception:
                    enabled_skill_names = []

    # 将启用的 Skill 正文注入 system prompt
    if enabled_skill_names:
        skill_sections = []
        for name in enabled_skill_names:
            skill = get_skill(name)
            if skill:
                skill_sections.append(
                    f"## {skill.name}\n目录: {skill.skill_dir}\n\n{skill.body}"
                )
        if skill_sections:
            system_prompt += "\n\n---\n\n# 可用技能\n\n" + "\n\n---\n\n".join(skill_sections)

    # —— 第4步：创建引擎并注册全部工具 ——
    engine = await create_engine(session_id=session_id, system_prompt=system_prompt, provider_name=model_id)

    for tool in get_schemas():
        t = get_tool(tool["name"])
        if t:
            engine.register_tool(tool, t.run)

    return {"task_id": engine.task_id, "session_id": session_id}


@router.get("/{task_id}/stream")
async def stream_chat(task_id: str):
    """SSE 流式端点：从数据库加载历史消息，压缩后送入引擎执行，逐事件推送给前端"""
    engine = get_engine(task_id)
    if not engine:
        async def not_found():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Task not found'})}\n\n"
        return StreamingResponse(not_found(), media_type="text/event-stream")

    # —— 加载历史消息 ——
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
            (engine.session_id,),
        )
        rows = await cursor.fetchall()
        session_row = await db.execute("SELECT agent_id FROM sessions WHERE id = ?", (engine.session_id,))
        session = await session_row.fetchone()

    messages = []
    for r in rows:
        if r["role"] in ("user", "assistant"):
            messages.append({"role": r["role"], "content": r["content"] or ""})

    # —— 获取 Agent 级别的压缩配置（优先于全局配置）——
    agent_compress_cfg = None
    if session and session["agent_id"]:
        async with get_db() as db:
            row = await db.execute("SELECT compress_config FROM agents WHERE id = ?", (session["agent_id"],))
            agent = await row.fetchone()
            if agent:
                try:
                    raw_compress = agent["compress_config"]
                    if isinstance(raw_compress, str) and raw_compress.strip():
                        agent_compress_cfg = json.loads(raw_compress)
                    elif isinstance(raw_compress, dict):
                        agent_compress_cfg = raw_compress
                except Exception:
                    agent_compress_cfg = None

    compress_cfg = agent_compress_cfg or get_settings().get("compress", {})
    messages_for_engine = compress_messages(messages, compress_cfg)

    async def event_stream():
        """SSE 事件生成器：逐条产出引擎事件"""
        assistant_content = ""
        model_name = getattr(engine.provider, "model", "unknown")
        last_step = 0
        cost_logged = False
        try:
            async for event in engine.run(messages_for_engine):
                event_type = event.get("type", "unknown")
                step = event.get("step")
                if isinstance(step, int):
                    last_step = step

                # 记录执行链路
                trace_detail = {}
                if event_type == "tool_call":
                    trace_detail = {"tool": event.get("tool"), "input": event.get("input")}
                elif event_type == "tool_result":
                    trace_detail = {"tool": event.get("tool"), "output": str(event.get("output", ""))[:500]}
                elif event_type in ("error", "slow_think"):
                    trace_detail = {"message": event.get("message") or event.get("content")}
                await log_trace(engine.session_id, task_id, last_step or None, event_type, trace_detail)

                # 累积文本 + 结束时写入 Token 成本
                if event_type == "text_delta":
                    assistant_content += event["content"]
                elif event_type in ("done", "error", "interrupted") and not cost_logged:
                    usage = event.get("usage", {}) if isinstance(event, dict) else {}
                    input_tokens = usage.get("input_tokens", engine.total_input_tokens)
                    output_tokens = usage.get("output_tokens", engine.total_output_tokens)
                    await log_cost(
                        session_id=engine.session_id,
                        task_id=task_id,
                        model=model_name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    cost_logged = True

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 保存 assistant 最终回复到数据库
            if assistant_content:
                now = datetime.utcnow().isoformat()
                async with get_db() as db2:
                    await db2.execute(
                        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                        (str(uuid.uuid4()), engine.session_id, assistant_content, now),
                    )
                    await db2.commit()
        finally:
            remove_engine(task_id)  # 无论成功或失败，清理引擎

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # 禁用 nginx 缓冲
    )


@router.post("/{task_id}/interrupt")
async def interrupt_chat(task_id: str):
    ok = interrupt_engine(task_id)
    return {"success": ok}

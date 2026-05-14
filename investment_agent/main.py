from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from .app.db import init_db
from .app.api.chat import router as chat_router
from .app.api.sessions import router as sessions_router
from .app.api.settings import router as settings_router
from .app.api.agents import router as agents_router
from .app.api.skills import router as skills_router
from .app.api.observability import router as observability_router

# 项目根目录（investment_agent/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "investment_agent" / "app" / "static"
TEMPLATE_DIR = PROJECT_ROOT / "investment_agent" / "app" / "templates"
OUTPUT_DIR = PROJECT_ROOT / "output"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

TABS = [
    {"label": "对话", "href": "/"},
    {"label": "Agent", "href": "/agents"},
    {"label": "Skills", "href": "/skills"},
    {"label": "模型", "href": "/settings"},
    {"label": "历史", "href": "/history"},
    {"label": "统计", "href": "/observability"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库和输出目录"""
    await init_db()
    (OUTPUT_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "charts").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Investment Agent", lifespan=lifespan)

# —— 注册 API 路由 ——
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(skills_router)
app.include_router(observability_router)

# —— 静态文件（前端 HTML/JS/CSS）——
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "tabs": TABS, "active_tab": "对话"})


@app.get("/agents")
async def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {"request": request, "tabs": TABS, "active_tab": "Agent"})


@app.get("/skills")
async def skills_page(request: Request):
    return templates.TemplateResponse("skills.html", {"request": request, "tabs": TABS, "active_tab": "Skills"})


@app.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request, "tabs": TABS, "active_tab": "模型"})


@app.get("/history")
async def history_page(request: Request):
    return templates.TemplateResponse("history.html", {"request": request, "tabs": TABS, "active_tab": "历史"})


@app.get("/observability")
async def observability_page(request: Request):
    return templates.TemplateResponse("observability.html", {"request": request, "tabs": TABS, "active_tab": "统计"})


@app.get("/health")
async def health():
    return {"status": "ok"}

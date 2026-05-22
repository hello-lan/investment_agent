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
from .app.api.files import router as files_router
from .app.api.observability import router as observability_router
from .app.api.tools import router as tools_router
from .agent.skills.loader import init_skills_dir
from .agent.tools.run_command import set_project_root
from .config import get_settings

# 项目根目录（investment_agent/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "investment_agent" / "app" / "static"
TEMPLATE_DIR = PROJECT_ROOT / "investment_agent" / "app" / "templates"
OUTPUT_DIR = PROJECT_ROOT / "output"
DATA_DIR = PROJECT_ROOT / "data"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

TABS = [
    {"label": "对话", "href": "/"},
    {"label": "Agent", "href": "/agents"},
    {"label": "Skills", "href": "/skills"},
    {"label": "模型", "href": "/model"},
    {"label": "文件", "href": "/files"},
    {"label": "统计", "href": "/observability"},
]


def _resolve_skills_dir() -> Path:
    """解析 Skills 目录路径（支持相对路径，相对于项目根目录）"""
    settings = get_settings()
    skills_cfg = settings.get("skills", {}) if isinstance(settings.get("skills", {}), dict) else {}
    raw_dir = str(skills_cfg.get("directory", "./skills")).strip() or "./skills"
    path = Path(raw_dir)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库、输出目录、Skills、全局依赖"""
    await init_db()
    (OUTPUT_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "charts").mkdir(parents=True, exist_ok=True)
    # 注入 agent 包所需的全局依赖
    set_project_root(str(PROJECT_ROOT))
    init_skills_dir(_resolve_skills_dir())
    yield


app = FastAPI(title="Investment Agent", lifespan=lifespan)

# —— 注册 API 路由 ——
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(skills_router)
app.include_router(files_router)
app.include_router(observability_router)
app.include_router(tools_router)

# —— 静态文件（前端 HTML/JS/CSS）——
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/data-files", StaticFiles(directory=str(DATA_DIR)), name="data-files")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "tabs": TABS, "active_tab": "对话"})


@app.get("/agents")
async def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {"request": request, "tabs": TABS, "active_tab": "Agent"})


@app.get("/skills")
async def skills_page(request: Request):
    return templates.TemplateResponse("skills.html", {"request": request, "tabs": TABS, "active_tab": "Skills"})


@app.get("/model")
async def settings_page(request: Request):
    return templates.TemplateResponse("model.html", {"request": request, "tabs": TABS, "active_tab": "模型"})


@app.get("/files")
async def files_page(request: Request):
    return templates.TemplateResponse("files.html", {"request": request, "tabs": TABS, "active_tab": "文件"})


@app.get("/observability")
async def observability_page(request: Request):
    return templates.TemplateResponse("observability.html", {"request": request, "tabs": TABS, "active_tab": "统计"})


@app.get("/health")
async def health():
    return {"status": "ok"}

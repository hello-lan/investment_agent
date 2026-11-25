from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from .app.db import init_db
from .app.api.chat import router as chat_router
from .app.api.sessions import router as sessions_router
from .app.api.settings import router as settings_router
from .app.api.agents import router as agents_router
from .app.api.subagents import router as subagents_router
from .app.api.skills import router as skills_router
from .app.api.files import router as files_router
from .app.api.observability import router as observability_router
from .app.api.tools import router as tools_router
from .app.api.stock_dashboard import router as stock_dashboard_router
from .agent.skills.loader import init_skills_dir
from .agent.tools.http_retrieve import set_instance_loaders
from .agent.tools.run_command import set_project_root
from .app.services.tool_instances import get_tool_instance, list_tool_instances
from .app.services.subagent_seed import load_builtin_subagents, migrate_seeded_builtins
from .config import ROOT_DIR, resolve_skills_dir

STATIC_DIR = ROOT_DIR / "investment_agent" / "app" / "static"
TEMPLATE_DIR = ROOT_DIR / "investment_agent" / "app" / "templates"
DATA_DIR = ROOT_DIR / "data"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

TABS = [
    {"label": "对话", "href": "/"},
    {"label": "Agent", "href": "/agents"},
    {"label": "Skills", "href": "/skills"},
    {"label": "工具", "href": "/tools"},
    {"label": "模型", "href": "/model"},
    {"label": "看板", "href": "/dashboard"},
    {"label": "统计", "href": "/observability"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库、Skills、全局依赖"""
    await init_db()
    await load_builtin_subagents()
    await migrate_seeded_builtins()
    # 注入 agent 包所需的全局依赖
    set_project_root(str(ROOT_DIR))
    set_instance_loaders(get_tool_instance, list_tool_instances)
    init_skills_dir(resolve_skills_dir())
    yield


app = FastAPI(title="Investment Agent", lifespan=lifespan)

# —— 注册 API 路由 ——
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(subagents_router)
app.include_router(skills_router)
app.include_router(files_router)
app.include_router(observability_router)
app.include_router(tools_router)
app.include_router(stock_dashboard_router)

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


@app.get("/tools")
async def tools_page(request: Request):
    return templates.TemplateResponse("tools.html", {"request": request, "tabs": TABS, "active_tab": "工具"})


@app.get("/model")
async def settings_page(request: Request):
    return templates.TemplateResponse("model.html", {"request": request, "tabs": TABS, "active_tab": "模型"})


@app.get("/dashboard")
async def dashboard_page(request: Request):
    return templates.TemplateResponse("stock_dashboard.html", {"request": request, "tabs": TABS, "active_tab": "看板"})


@app.get("/observability")
async def observability_page(request: Request):
    return templates.TemplateResponse("observability.html", {"request": request, "tabs": TABS, "active_tab": "统计"})


@app.get("/health")
async def health():
    return {"status": "ok"}

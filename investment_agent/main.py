from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from .app.db import init_db
from .app.api.chat import router as chat_router
from .app.api.sessions import router as sessions_router
from .app.api.settings import router as settings_router
from .app.api.agents import router as agents_router
from .app.api.skills import router as skills_router
from .app.api.observability import router as observability_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "investment_agent" / "app" / "static"
OUTPUT_DIR = PROJECT_ROOT / "output"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    (OUTPUT_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "charts").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Investment Agent", lifespan=lifespan)

app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(skills_router)
app.include_router(observability_router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/agents")
async def agents_page():
    return FileResponse(str(STATIC_DIR / "agents.html"))


@app.get("/skills")
async def skills_page():
    return FileResponse(str(STATIC_DIR / "skills.html"))


@app.get("/settings")
async def settings_page():
    return FileResponse(str(STATIC_DIR / "settings.html"))


@app.get("/history")
async def history_page():
    return FileResponse(str(STATIC_DIR / "history.html"))


@app.get("/observability")
async def observability_page():
    return FileResponse(str(STATIC_DIR / "observability.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}

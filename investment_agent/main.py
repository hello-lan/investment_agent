from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from db import init_db
from api.chat import router as chat_router
from api.sessions import router as sessions_router
from api.settings import router as settings_router
from api.agents import router as agents_router
from api.observability import router as observability_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    import os
    os.makedirs("output/reports", exist_ok=True)
    os.makedirs("output/charts", exist_ok=True)
    yield


app = FastAPI(title="Investment Agent", lifespan=lifespan)

app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(observability_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/agents")
async def agents_page():
    return FileResponse("static/agents.html")


@app.get("/settings")
async def settings_page():
    return FileResponse("static/settings.html")


@app.get("/history")
async def history_page():
    return FileResponse("static/history.html")


@app.get("/observability")
async def observability_page():
    return FileResponse("static/observability.html")


@app.get("/health")
async def health():
    return {"status": "ok"}

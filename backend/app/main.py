"""AgentFlow FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, reports, runs, settings, tools
from app.config import ensure_dirs
from app.seed import ensure_seed_tools
from app.storage import db, demo_db
from app.utils.limits import RateLimitMiddleware
from app.utils.logging import get_logger

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.init_db()
    ensure_seed_tools()
    demo_db.ensure_demo_db()
    db.fail_stale_runs()
    logger.info("AgentFlow 启动完成")
    yield


app = FastAPI(
    title="AgentFlow API",
    description="多智能体任务编排工作台后端",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(settings.router)
app.include_router(tools.router)
app.include_router(reports.router)
app.include_router(runs.router)

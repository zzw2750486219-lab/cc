from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from api.middleware import AccessLogMiddleware, RequestIDMiddleware
from api.routes.tasks import router as tasks_router, store, task_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger("agent-platform.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("WORKER_ENABLED", "1") != "1":
        yield
        return

    from orchestrator.worker import OrchestratorWorker

    concurrency = int(os.getenv("WORKER_CONCURRENCY", "2"))
    worker = OrchestratorWorker(
        queue=task_queue,
        task_store=store,
        concurrency=concurrency,
    )
    worker_task = asyncio.create_task(worker.start())
    logger.info("worker started concurrency=%d", concurrency)

    yield

    logger.info("shutting down worker")
    await worker.stop()
    try:
        await asyncio.wait_for(worker_task, timeout=10)
    except asyncio.TimeoutError:
        worker_task.cancel()
    logger.info("worker stopped")


app = FastAPI(
    title="Cloud Agent Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(AccessLogMiddleware)

app.include_router(tasks_router)

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}

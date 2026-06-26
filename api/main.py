from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

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


@app.get("/health")
async def health():
    return {"status": "ok"}

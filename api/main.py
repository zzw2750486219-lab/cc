from __future__ import annotations

import logging

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.middleware import AccessLogMiddleware, RequestIDMiddleware
from api.routes.tasks import router as tasks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(title="Cloud Agent Platform", version="0.1.0")

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

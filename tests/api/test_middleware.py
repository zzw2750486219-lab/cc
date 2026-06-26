from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from api.middleware import AccessLogMiddleware, RequestIDMiddleware


async def _test_endpoint(request):
    return JSONResponse({"ok": True})


def _make_app(middlewares):
    app = Starlette()
    for mw in middlewares:
        app.add_middleware(mw)
    app.router.add_route("/test", _test_endpoint)
    return app


class TestRequestIDMiddleware:
    def test_generates_request_id_when_missing(self):
        app = _make_app([RequestIDMiddleware])
        client = TestClient(app)

        resp = client.get("/test")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) == 12

    def test_propagates_existing_request_id(self):
        app = _make_app([RequestIDMiddleware])
        client = TestClient(app)

        resp = client.get("/test", headers={"X-Request-ID": "my-custom-id"})
        assert resp.headers["X-Request-ID"] == "my-custom-id"


class TestAccessLogMiddleware:
    def test_request_passes_through(self, caplog):
        import logging

        app = _make_app([AccessLogMiddleware])
        client = TestClient(app)

        with caplog.at_level(logging.INFO, logger="agent-platform.api"):
            resp = client.get("/test")
            assert resp.status_code == 200

        log_records = [r for r in caplog.records if "/test" in r.getMessage()]
        assert len(log_records) >= 1

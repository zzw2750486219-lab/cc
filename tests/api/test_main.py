from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


class TestAppSetup:
    def test_app_title(self):
        assert app.title == "Cloud Agent Platform"

    def _collect_routes(self, routes, paths):
        for r in routes:
            if hasattr(r, "path"):
                paths.append(r.path)
            if hasattr(r, "routes"):
                self._collect_routes(r.routes, paths)
            elif hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                self._collect_routes(r.original_router.routes, paths)

    def test_routes_registered(self):
        route_paths: list[str] = []
        self._collect_routes(app.routes, route_paths)
        assert "/health" in route_paths
        assert "/api/v1/tasks" in route_paths
        assert "/api/v1/tasks/{task_id}" in route_paths
        assert "/api/v1/tasks/{task_id}/stream" in route_paths
        assert "/api/v1/tasks/{task_id}/cancel" in route_paths

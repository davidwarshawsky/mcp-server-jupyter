from src.config import settings
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route
from src.main import health_check


def test_settings_defaults():
    assert isinstance(settings.MCP_MEMORY_LIMIT_BYTES, int)
    assert settings.MCP_IO_POOL_SIZE >= 0


def test_health_check_endpoint():
    app = Starlette(routes=[Route("/health", health_check)])
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "healthy"
    assert "active_kernels" in j
    assert "version" in j

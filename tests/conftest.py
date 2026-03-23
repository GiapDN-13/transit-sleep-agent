"""
Pytest fixtures cho test suite.
"""
import contextlib
import unittest.mock as mock
import pytest


def _make_app_client():
    """
    Tạo TestClient với lifespan bị thay bằng no-op để tránh kết nối Telegram thật.
    ExtBot dùng __setattr__ protection nên không thể mock.patch.object trực tiếp
    → thay toàn bộ lifespan_context trên router.
    """
    import backend.main as m

    @contextlib.asynccontextmanager
    async def _noop_lifespan(app):
        yield  # Bỏ qua bot init, webhook, scheduler — tests tự gọi khi cần

    m.app.router.lifespan_context = _noop_lifespan

    from fastapi.testclient import TestClient
    client = TestClient(m.app, raise_server_exceptions=True)
    return client, m.bot_app


@pytest.fixture
def client():
    """FastAPI TestClient với bot lifecycle bị mock."""
    c, _ = _make_app_client()
    yield c


@pytest.fixture
def bot_app():
    """bot_app instance (cùng app với client fixture)."""
    _, app = _make_app_client()
    yield app

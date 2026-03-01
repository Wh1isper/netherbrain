import pytest
from fastapi.testclient import TestClient

from netherbrain.agent_runtime.app import app


@pytest.mark.integration
def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "postgres" in data
        assert "redis" in data

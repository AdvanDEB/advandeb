from fastapi.testclient import TestClient

from advandeb_mcp.server import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ok"
    assert "ollama_model" in payload

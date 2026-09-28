"""Smoke tests for the FastAPI backend."""

import os

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    os.environ["COGNITO_BYPASS_USER_ID"] = "test-user"
    os.environ["COGNITO_BYPASS_TENANT_ID"] = "test-tenant"
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_config(client):
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert "qdrant_url" in data
    assert "qdrant_api_key" in data
    # Sensitive values should be masked when not revealed.
    assert data["qdrant_api_key"].startswith("*")


def test_documents_list(client):
    # Requires valid AWS credentials to be present; listing is sufficient smoke check.
    r = client.get("/documents")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data

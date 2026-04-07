"""Smoke tests for observability endpoints — no DB required."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_ready_db_healthy():
    with patch("app.main.check_db_health", return_value=True):
        resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_ready_db_unhealthy():
    with patch("app.main.check_db_health", return_value=False):
        resp = client.get("/ready")
    assert resp.status_code == 503

"""Request guards: body-size cap and proxy-aware client address."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MOLIDO_JWT_SECRET", "request-guards-test-secret-minimum-32")
os.environ.setdefault("MOLIDO_DATA_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
os.environ.setdefault("MOLIDO_DB_PATH", str(Path(tempfile.gettempdir()) / "molido-request-guards-tests.sqlite3"))

from fastapi.testclient import TestClient
from starlette.requests import Request

import app


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "guards.sqlite3")
    app.init_db()
    return TestClient(app.app)


def fake_request(ip: str, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (ip, 50000), "query_string": b""})


def test_an_oversized_body_is_rejected_before_reaching_the_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.post("/v1/auth/login", content=b"x" * (app.MAX_REQUEST_BYTES + 1),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


def test_normal_requests_still_pass(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200


def test_forwarded_for_is_ignored_unless_the_proxy_is_trusted(monkeypatch):
    monkeypatch.setattr(app, "TRUST_PROXY_HEADERS", False)
    assert app.client_ip(fake_request("10.0.0.5", "203.0.113.9, 10.0.0.1")) == "10.0.0.5"


def test_forwarded_for_is_used_when_the_proxy_is_trusted(monkeypatch):
    monkeypatch.setattr(app, "TRUST_PROXY_HEADERS", True)
    assert app.client_ip(fake_request("10.0.0.5", "203.0.113.9, 10.0.0.1")) == "203.0.113.9"
    assert app.client_ip(fake_request("10.0.0.5")) == "10.0.0.5"

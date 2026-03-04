from fastapi.testclient import TestClient

from app.config import get_settings


def build_token_protected_app(monkeypatch) -> TestClient:
    monkeypatch.setenv("BROWSER_MODE", "mock")
    monkeypatch.setenv("RUN_STORE_BACKEND", "in_memory")
    monkeypatch.setenv("FILESYSTEM_MODE", "local")
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret-token")
    get_settings.cache_clear()
    from app.main import build_app

    app = build_app()
    return TestClient(app)


def test_protected_endpoints_require_token(monkeypatch) -> None:
    payload = {
        "run_name": "auth-test",
        "steps": [{"type": "wait", "until": "timeout", "ms": 1}],
    }

    with build_token_protected_app(monkeypatch) as client:
        create_run = client.post("/api/runs", json=payload)
        assert create_run.status_code == 401

        plan = client.post("/api/plan", json={"task": "Open https://example.com"})
        assert plan.status_code == 401

        imported = client.post(
            "/api/test-cases/import",
            files={"file": ("steps.csv", b"type,selector\nclick,#btn", "text/csv")},
        )
        assert imported.status_code == 401

    get_settings.cache_clear()


def test_protected_endpoints_accept_valid_token(monkeypatch) -> None:
    payload = {
        "run_name": "auth-test",
        "steps": [{"type": "wait", "until": "timeout", "ms": 1}],
    }

    with build_token_protected_app(monkeypatch) as client:
        create_run = client.post(
            "/api/runs",
            json=payload,
            headers={"X-Admin-Token": "secret-token"},
        )
        assert create_run.status_code == 200
        run_id = create_run.json()["run_id"]

        cancel = client.post(
            f"/api/runs/{run_id}/cancel",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert cancel.status_code == 200

        plan = client.post(
            "/api/plan",
            json={"task": "Open https://example.com"},
            headers={"X-Admin-Token": "secret-token"},
        )
        assert plan.status_code == 200

        imported = client.post(
            "/api/test-cases/import",
            files={"file": ("steps.csv", b"type,selector\nclick,#btn", "text/csv")},
            headers={"X-Admin-Token": "secret-token"},
        )
        assert imported.status_code == 200

    get_settings.cache_clear()

import os

from fastapi.testclient import TestClient

os.environ.setdefault("BROWSER_MODE", "mock")
os.environ.setdefault("RUN_STORE_BACKEND", "in_memory")
os.environ.setdefault("FILESYSTEM_MODE", "local")
os.environ["ADMIN_API_TOKEN"] = ""

from app.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "llm" in body


def test_run_creation_and_completion() -> None:
    payload = {
        "run_name": "test-run",
        "start_url": "https://example.com",
        "steps": [
            {"type": "wait", "until": "timeout", "ms": 50},
            {
                "type": "verify_text",
                "selector": "h1",
                "match": "contains",
                "value": "Example",
            },
        ],
    }

    with TestClient(app) as client:
        created = client.post("/api/runs", json=payload)
        assert created.status_code == 200

        run_id = created.json()["run_id"]
        fetched = client.get(f"/api/runs/{run_id}")

    assert fetched.status_code == 200
    run = fetched.json()
    assert run["status"] == "completed"
    assert run["summary"]
    assert len(run["steps"]) == 2
    assert all(step["status"] == "completed" for step in run["steps"])


def test_run_rejects_when_step_count_exceeds_limit() -> None:
    payload = {
        "run_name": "too-many-steps",
        "steps": [{"type": "click", "selector": "button.x"}] * 21,
    }

    with TestClient(app) as client:
        response = client.post("/api/runs", json=payload)

    assert response.status_code == 400
    assert "max_steps_per_run" in response.json()["detail"]


def test_run_accepts_test_data_and_selector_profile() -> None:
    payload = {
        "run_name": "profiled-run",
        "test_data": {
            "email": "qa@example.com",
            "password": "secret123",
        },
        "selector_profile": {
            "email": "#username",
            "password": ["#password", "input[name='password']"],
        },
        "steps": [
            {
                "type": "type",
                "selector": "{{selector.email}}",
                "text": "{{email}}",
            },
            {
                "type": "type",
                "selector": "{{selector.password}}",
                "text": "{{password}}",
            },
        ],
    }

    with TestClient(app) as client:
        created = client.post("/api/runs", json=payload)
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]

        fetched = client.get(f"/api/runs/{run_id}")
        assert fetched.status_code == 200, fetched.text

    body = fetched.json()
    assert body["test_data"]["email"] == "qa@example.com"
    assert body["selector_profile"]["email"] == ["#username"]
    assert body["selector_profile"]["password"] == ["#password", "input[name='password']"]

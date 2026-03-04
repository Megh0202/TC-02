import os
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

os.environ.setdefault("BROWSER_MODE", "mock")
os.environ.setdefault("RUN_STORE_BACKEND", "in_memory")
os.environ.setdefault("FILESYSTEM_MODE", "local")
os.environ["ADMIN_API_TOKEN"] = ""

from app.main import app


def test_import_csv_steps() -> None:
    csv_content = (
        "type,url,selector,text,match,value,ms\n"
        "navigate,https://example.com,,,,,\n"
        "wait,,,,,,500\n"
        "verify_text,,h1,,contains,Example Domain,\n"
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/test-cases/import",
            data={"run_name": "Create_Form_01"},
            files={"file": ("steps.csv", csv_content.encode("utf-8"), "text/csv")},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_name"] == "Create_Form_01"
    assert body["source_filename"] == "steps.csv"
    assert body["imported_count"] == 3
    assert [step["type"] for step in body["steps"]] == ["navigate", "wait", "verify_text"]


def test_import_xlsx_steps() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["type", "selector", "text", "clear_first"])
    sheet.append(["type", "#username", "qa@example.com", "true"])
    sheet.append(["type", "#password", "secret123", "false"])

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    with TestClient(app) as client:
        response = client.post(
            "/api/test-cases/import",
            files={
                "file": (
                    "login_steps.xlsx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_name"] == "login_steps"
    assert body["imported_count"] == 2
    assert body["steps"][0]["clear_first"] is True
    assert body["steps"][1]["clear_first"] is False


def test_import_rejects_invalid_file_type() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/test-cases/import",
            files={"file": ("steps.txt", b"type,selector\nclick,#btn", "text/plain")},
        )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]

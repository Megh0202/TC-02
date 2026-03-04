# Backend

## Run

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Env
Copy root `.env.example` to `.env` and edit values as needed.

Backend requires `BRAIN_BASE_URL` (default `http://localhost:8090`) and calls the brain service for summaries and model metadata.
Runs are persisted by default in SQLite (`RUN_STORE_BACKEND=sqlite`, `RUN_STORE_DB_PATH=data/run_store.sqlite3`).
Selector learning memory can be enabled to reuse successful selectors across runs:
- `SELECTOR_MEMORY_ENABLED=true`
- `SELECTOR_MEMORY_BACKEND=sqlite|in_memory|disabled`
- `SELECTOR_MEMORY_DB_PATH=data/selector_memory.sqlite3`
- `SELECTOR_MEMORY_MAX_CANDIDATES=5`

Selector recovery retries can be configured for transient UI timing issues:
- `SELECTOR_RECOVERY_ENABLED=true`
- `SELECTOR_RECOVERY_ATTEMPTS=2`
- `SELECTOR_RECOVERY_DELAY_MS=350`

The executor also supports built-in runtime macros in text fields, for example:
- `{{NOW_YYYYMMDD_HHMMSS}}`
- `{{NOW}}`
- `{{UUID}}`
To protect admin endpoints, set `ADMIN_API_TOKEN` (when set, POST `/api/plan`, POST `/api/runs`, and POST `/api/runs/{run_id}/cancel` require `X-Admin-Token` or `Authorization: Bearer <token>`).
Filesystem integration supports:
- `FILESYSTEM_MODE=local` (local adapter)
- `FILESYSTEM_MODE=mcp` (real MCP server via `@modelcontextprotocol/server-filesystem`)

For real browser execution, set `BROWSER_MODE=playwright` and install browser binaries once:

```bash
python -m playwright install chromium
```

For strict Browser MCP integration, set:

```bash
BROWSER_MODE=mcp
BROWSER_MCP_COMMAND=npx
BROWSER_MCP_PACKAGE=@playwright/mcp@latest
```

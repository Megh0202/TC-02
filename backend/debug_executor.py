import asyncio
import sys
import traceback
from datetime import datetime, timezone
from app.config import get_settings
from app.runtime.executor import AgentExecutor
from app.brain.http_client import HttpBrainClient
from app.runtime.store import SqliteRunStore
from app.mcp.browser_client import build_browser_client
from app.mcp.filesystem_client import build_filesystem_client
from app.runtime.selector_memory import build_selector_memory_store
from app.schemas import RunCreateRequest, RunState, StepRuntimeState
from uuid import uuid4

async def test():
    try:
        s = get_settings()
        print(f"Settings loaded", file=sys.stderr)
        
        brain_client = HttpBrainClient(s)
        run_store = SqliteRunStore(s.run_store_db_path)
        browser_client = build_browser_client(s)
        file_client = build_filesystem_client(s)
        selector_memory = build_selector_memory_store(s)
        
        executor = AgentExecutor(
            settings=s,
            brain_client=brain_client,
            run_store=run_store,
            browser_client=browser_client,
            file_client=file_client,
            selector_memory_store=selector_memory,
        )
        
        # Create a simple run
        run_id = str(uuid4())
        now = datetime.now(timezone.utc)
        run = RunState(
            run_id=run_id,
            run_name="test-debug",
            start_url="https://example.com",
            prompt="Open the page",
            execution_mode="autonomous",
            status="pending",
            created_at=now,
            started_at=None,
            finished_at=None,
            steps=[],
            summary="",
            test_data={},
            selector_profile={},
        )
        run_store.persist(run)
        print(f"Run created: {run_id}", file=sys.stderr)
        
        # Execute it
        await executor.execute(run_id)
        print(f"Execution complete", file=sys.stderr)
        
        # Check result
        result = run_store.get(run_id)
        print(f"Final status: {result.status}")
        print(f"Summary: {result.summary}")
        
    except Exception as e:
        print(f"\n=== EXCEPTION ===", file=sys.stderr)
        print(f"Type: {type(e).__name__}", file=sys.stderr)
        print(f"Message: {e}", file=sys.stderr)
        print(f"\nTraceback:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

asyncio.run(test())

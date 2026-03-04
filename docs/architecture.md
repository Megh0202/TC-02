# High-Level Architecture

## Layers
1. Next.js UI
2. FastAPI Agent API
3. Agent Runtime (planner + executor)
4. Brain Service API (separate service boundary for LLM logic)
5. Adapter layer
   - Browser adapter (`mock` or `playwright`)
   - MCP Tool Adapter (`filesystem`)

## Execution model
- UI submits task with ordered steps
- API validates schema and creates run
- Executor processes steps sequentially with retries/timeouts
- Tool adapters execute browser/file actions
- Backend calls Brain Service for summaries/plans
- Verifiers evaluate text/image assertions
- API streams or polls run status back to UI

## Config strategy
- Backend uses `BRAIN_BASE_URL` and optional `BRAIN_API_KEY`
- Brain service owns `LLM_MODE` and provider-specific secrets
- UI never receives provider secret data

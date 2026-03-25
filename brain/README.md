# Brain Service

Standalone LLM service for Tekno Phantom Agent.

## Run

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8090
```

## Env

Copy root `.env.example` to `.env` and set:

- `LLM_MODE=local` for vLLM or `LLM_MODE=cloud` for a cloud provider
- `CLOUD_PROVIDER=auto` to switch automatically from the configured API key, or set `openai` / `anthropic`
- `ANTHROPIC_API_KEY` for Claude Sonnet or `OPENAI_API_KEY` for OpenAI
- optional `BRAIN_API_KEY` for backend-to-brain auth

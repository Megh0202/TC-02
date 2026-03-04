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

- `LLM_MODE=local` for vLLM or `LLM_MODE=cloud` for OpenAI
- `OPENAI_API_KEY` when using cloud mode
- optional `BRAIN_API_KEY` for backend-to-brain auth

# Product Requirements (Phase 1)

## Goal
Deliver an agent system where an end user submits a multi-step browser task, and the system executes each step with traceable status using an admin-selected LLM mode (`local` or `cloud`).

## Core Functional Scope
1. Local LLM mode through `vLLM`
2. Cloud LLM mode through `OpenAI`
3. Browser actions: click, select, scroll, type, wait, popup handling
4. Verification: text and image
5. File System MCP access for task artifacts and controlled file operations
6. Next.js web UI for creating and executing multi-step tasks
7. Brain/Agent separation: LLM provider logic runs in standalone brain service; agent only calls brain APIs

## Non-Functional Priorities
- Determinism: explicit action schema, predictable execution engine
- Safety: domain allowlist, bounded step count and timeout, cancellation
- Observability: run timeline, per-step status, errors, artifacts
- Replaceability: provider abstraction for LLM and MCP tools

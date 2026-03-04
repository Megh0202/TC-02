from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Protocol

from app.config import Settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SelectorMemoryStore(Protocol):
    def remember_success(self, domain: str, step_type: str, key: str, selector: str) -> None:
        ...

    def get_candidates(self, domain: str, step_type: str, key: str, limit: int = 5) -> list[str]:
        ...


def _normalize_token(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass
class _MemoryItem:
    selector: str
    score: int


class InMemorySelectorMemoryStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._entries: dict[tuple[str, str, str], dict[str, _MemoryItem]] = {}

    def remember_success(self, domain: str, step_type: str, key: str, selector: str) -> None:
        domain_token = _normalize_token(domain)
        step_token = _normalize_token(step_type)
        key_token = _normalize_token(key)
        selector_token = selector.strip()
        if not (domain_token and step_token and key_token and selector_token):
            return

        lookup = (domain_token, step_token, key_token)
        with self._lock:
            slot = self._entries.setdefault(lookup, {})
            existing = slot.get(selector_token)
            if existing is None:
                slot[selector_token] = _MemoryItem(selector=selector_token, score=1)
            else:
                existing.score += 1

    def get_candidates(self, domain: str, step_type: str, key: str, limit: int = 5) -> list[str]:
        domain_token = _normalize_token(domain)
        step_token = _normalize_token(step_type)
        key_token = _normalize_token(key)
        if not (domain_token and step_token and key_token):
            return []

        lookup = (domain_token, step_token, key_token)
        with self._lock:
            values = list(self._entries.get(lookup, {}).values())

        values.sort(key=lambda item: item.score, reverse=True)
        return [item.selector for item in values[: max(limit, 1)]]


class SqliteSelectorMemoryStore(InMemorySelectorMemoryStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_from_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS selector_memory (
                    domain TEXT NOT NULL,
                    step_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    selector TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (domain, step_type, key, selector)
                )
                """
            )
            conn.commit()

    def _load_from_db(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT domain, step_type, key, selector, score FROM selector_memory"
            ).fetchall()
        for domain, step_type, key, selector, score in rows:
            lookup = (_normalize_token(domain), _normalize_token(step_type), _normalize_token(key))
            slot = self._entries.setdefault(lookup, {})
            slot[selector] = _MemoryItem(selector=selector, score=max(int(score), 1))

    def remember_success(self, domain: str, step_type: str, key: str, selector: str) -> None:
        super().remember_success(domain, step_type, key, selector)

        domain_token = _normalize_token(domain)
        step_token = _normalize_token(step_type)
        key_token = _normalize_token(key)
        selector_token = selector.strip()
        if not (domain_token and step_token and key_token and selector_token):
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO selector_memory (domain, step_type, key, selector, score, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(domain, step_type, key, selector) DO UPDATE SET
                    score = selector_memory.score + 1,
                    updated_at = excluded.updated_at
                """,
                (domain_token, step_token, key_token, selector_token, utc_now_iso()),
            )
            conn.commit()


class NoopSelectorMemoryStore:
    def remember_success(self, domain: str, step_type: str, key: str, selector: str) -> None:
        return

    def get_candidates(self, domain: str, step_type: str, key: str, limit: int = 5) -> list[str]:
        return []


def build_selector_memory_store(settings: Settings) -> SelectorMemoryStore:
    if not settings.selector_memory_enabled:
        return NoopSelectorMemoryStore()
    if settings.selector_memory_backend == "in_memory":
        return InMemorySelectorMemoryStore()
    if settings.selector_memory_backend == "sqlite":
        return SqliteSelectorMemoryStore(settings.selector_memory_db_path)
    return NoopSelectorMemoryStore()

"""Compatibility shim — `sqlite3-sag` is the successor to `project_memory`'s
journal core.

This package exists so code written as

    from project_memory import DEFAULT_KINDS, MemorySchema, ProjectMemory

keeps working against `sqlite3_sag` **unchanged**. It re-exports the journal
surface only — the append + recall + verify core — mapping the old names onto the
new primitive:

    MemorySchema  → sqlite3_sag.JournalSchema
    ProjectMemory → sqlite3_sag.SagJournal

It does NOT re-export the fuller `project_memory` library (the natural-language
*ask* surface, the synthesis-mud epistemic guard, the portfolio brain): those are
out of scope for the journal primitive and live in the original package.

⚠️  Do NOT co-install this shim alongside the original `project_memory`
distribution — the top-level name collides *by design* (this is the successor).
New code should import from `sqlite3_sag` directly.
"""

from __future__ import annotations

from sqlite3_sag import (
    DEFAULT_KINDS,
    FACT_STATUSES,
    SCHEMA_VERSION,
    InadmissiblePayload,
    JournalSchema,
    MemorySchema,
    ProjectMemory,
    SagJournal,
    check_payload,
    connect,
    invalidate_fact,
    record_fact,
    remember,
    verify,
)

__all__ = [
    "DEFAULT_KINDS",
    "FACT_STATUSES",
    "SCHEMA_VERSION",
    "MemorySchema",
    "JournalSchema",
    "ProjectMemory",
    "SagJournal",
    "remember",
    "record_fact",
    "invalidate_fact",
    "verify",
    "connect",
    "check_payload",
    "InadmissiblePayload",
]

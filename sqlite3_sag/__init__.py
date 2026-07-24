"""sqlite3-sag — the SAG journal as a tamper-evident, SQLite-native primitive.

A declared, append-only journal of typed entries with a **SHA-256 hash chain**
that makes the log *verifiable*: a recorded event cannot be silently altered,
reordered, or dropped without :func:`verify` reporting the first break. It is the
*persistence face* of refuse-to-pretend / committed-vs-observed — the same
discipline the retrieval side (declared-grep / declared-context) already ships.

Extracted from `project_memory`'s journal core (register-before-emit + append +
recall over the `declared_core` engine), generalized, and given the tamper-
evidence it did not have. Pure-Python, pure-stdlib, $0 by default (no loadable
extension, no numpy, no network) — see PROTOCOL.md for the versioned journal
protocol and ``fixtures/`` for the cross-provider conformance fixtures.

    from sqlite3_sag import SagJournal, JournalSchema, DEFAULT_KINDS

    j = SagJournal.open("journal.db",
                        JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))
    j.remember("retrieval 'auth' -> src/login.py [bm25]", kind="sag.retrieval",
               tags=["declared-grep", "bm25"])
    j.verify()          # → {"ok": True, "checked": 1, "head_hash": "...", ...}

Back-compat: the source library's ``ProjectMemory`` / ``MemorySchema`` names are
provided as aliases (and via the top-level ``project_memory`` compat shim), so
code written against ``project_memory``'s journal surface runs unchanged.
"""

from __future__ import annotations

from .chain import (
    CHAIN_VERSION,
    GENESIS,
    canonical_bytes,
    compute_hash,
    genesis,
    head_hash,
    preimage,
    verify,
)
from .ingest import invalidate_fact, record_fact, remember
from .payload import InadmissiblePayload, check_payload
from .query import ProjectMemory, SagJournal
from .schema import (
    DEFAULT_KINDS,
    FACT_STATUSES,
    SCHEMA_VERSION,
    JournalSchema,
    MemorySchema,
)
from .store import connect, new_id, now_iso

__version__ = "0.1.0"

# The versioned journal protocol this build implements (see PROTOCOL.md).
PROTOCOL_VERSION = "sag-journal/0.1-draft"


def open_journal(
    path: str = ":memory:",
    schema: JournalSchema | None = None,
    **kw: object,
) -> SagJournal:
    """Convenience: open (or create) a journal. Thin wrapper over ``SagJournal.open``."""
    return SagJournal.open(path, schema, **kw)


__all__ = [
    "__version__",
    "PROTOCOL_VERSION",
    # the main object (+ back-compat alias)
    "SagJournal",
    "ProjectMemory",
    "open_journal",
    # schema (+ back-compat alias)
    "JournalSchema",
    "MemorySchema",
    "DEFAULT_KINDS",
    "FACT_STATUSES",
    "SCHEMA_VERSION",
    # writing (functional form)
    "remember",
    "record_fact",
    "invalidate_fact",
    # tamper-evidence
    "verify",
    "head_hash",
    "compute_hash",
    "preimage",
    "canonical_bytes",
    "genesis",
    "GENESIS",
    "CHAIN_VERSION",
    # payload gate
    "check_payload",
    "InadmissiblePayload",
    # store
    "connect",
    "new_id",
    "now_iso",
]

"""SagJournal — the one object most callers use.

It owns a SQLite connection + a `JournalSchema`, appends hash-chained entries and
facts, answers questions by delegating retrieval to `declared_core.hybrid_query`
(BM25 + structural expansion along the entry→fact link + intent-adaptive fusion),
and can `verify()` its own tamper-evident chain.

    j = SagJournal.open("journal.db")               # or .open() for in-memory
    j.remember("we chose SQLite over Postgres", kind="decision")
    j.recall("database choice")                     # → ranked entry + fact hits
    j.verify()                                       # → {"ok": True, ...}
    j.head_hash()                                    # → checkpoint anchor

This is the journal *core* extracted from `project_memory`: the append + recall +
verify surface. The natural-language *ask* layer, the synthesis-mud epistemic
guard, dense embedding, and the portfolio brain are NOT part of the primitive —
they stay in the fuller `project_memory` library. A dense (semantic) signal is a
documented v1.x booster; v1 recall is the $0 lexical + structural floor.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from declared_core import HybridResult, hybrid_query

from . import chain as _chain
from . import ingest as _ingest
from .schema import JournalSchema
from .store import connect, create_store

# Reserved scorer internals stripped from every projected hit.
_RESERVED = ("_text", "_tags")


class SagJournal:
    """A project's append-only, tamper-evident journal, recalled in natural language."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        schema: JournalSchema | None = None,
        *,
        dimensions: object | None = None,
        hash_key: Any = None,
    ) -> None:
        self.schema = schema or JournalSchema()
        self.conn = conn
        self.corpus = create_store(conn, self.schema, dimensions=dimensions)
        self._hash_key = hash_key

    @classmethod
    def open(
        cls,
        path: str = ":memory:",
        schema: JournalSchema | None = None,
        *,
        dimensions: object | None = None,
        hash_key: Any = None,
    ) -> "SagJournal":
        """Open (or create) a journal at ``path`` (``:memory:`` for ephemeral)."""
        return cls(connect(path), schema, dimensions=dimensions, hash_key=hash_key)

    # ── writing ──────────────────────────────────────────────────────────────
    def remember(self, content: str, **kw: Any) -> dict[str, Any]:
        """Append an entry (see ``ingest.remember`` for kwargs)."""
        kw.setdefault("hash_key", self._hash_key)
        return _ingest.remember(self.conn, self.schema, content, **kw)

    def record_fact(self, claim: str, **kw: Any) -> dict[str, Any]:
        """Write a durable fact (see ``ingest.record_fact`` for kwargs)."""
        return _ingest.record_fact(self.conn, self.schema, claim, **kw)

    def invalidate_fact(self, fact_id: str, **kw: Any) -> bool:
        return _ingest.invalidate_fact(self.conn, self.schema, fact_id, **kw)

    # ── tamper-evidence ───────────────────────────────────────────────────────
    def verify(self, *, key: Any = None) -> dict[str, Any]:
        """Walk the hash chain from genesis; return the first break (classified),
        or ``{"ok": True, ...}``. See :func:`sqlite3_sag.chain.verify`."""
        return _chain.verify(self.conn, self.schema, key=self._hash_key if key is None else key)

    def head_hash(self) -> str | None:
        """The current chain head's ``row_hash`` — checkpoint this out-of-band."""
        return _chain.head_hash(self.conn, self.schema)

    # ── reading ──────────────────────────────────────────────────────────────
    def recall(
        self,
        text: str,
        *,
        limit: int = 10,
        table: str | None = None,
        use_intent: bool = True,
        verbose: bool = False,
    ) -> list[dict[str, Any]]:
        """Search the journal; return ranked, projected hits (entries + facts)."""
        _, hits = self._run(text, limit=limit, table=table, use_intent=use_intent)
        return [self._project(h, verbose) for h in hits[:limit]]

    def recent(self, limit: int = 10, *, kind: str | None = None) -> list[dict[str, Any]]:
        """The most recent entries, newest first (optionally filtered by kind)."""
        sql = f"SELECT id, content, kind, batch, tags, created_at, seq FROM {self.schema.episode_table}"
        params: list[Any] = []
        if kind is not None:
            self.schema.validate_kind(kind)
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [
            {
                "id": r[0], "content": r[1], "kind": r[2], "batch": r[3],
                "tags": json.loads(r[4]) if r[4] else [], "created_at": r[5], "seq": r[6],
            }
            for r in self.conn.execute(sql, params).fetchall()
        ]

    def count(self) -> dict[str, int]:
        """How many entries and (active) facts are stored."""
        ep = int(self.conn.execute(
            f"SELECT COUNT(*) FROM {self.schema.episode_table}").fetchone()[0])
        ft = int(self.conn.execute(
            f"SELECT COUNT(*) FROM {self.schema.fact_table} WHERE status = 'active'").fetchone()[0])
        return {"episodes": ep, "facts": ft}

    def close(self) -> None:
        self.conn.close()

    # ── internals ──────────────────────────────────────────────────────────────
    def _run(
        self, text: str, *, limit: int, table: str | None, use_intent: bool
    ) -> tuple[HybridResult, list[dict[str, Any]]]:
        # Over-fetch when filtering to a single table so a filter can't starve it.
        fetch = max(limit * 3, limit + 10) if table else limit
        result = hybrid_query(
            text, self.corpus, self.conn,
            limit=fetch, dense=None, use_intent=use_intent,
        )
        hits = result.hits
        if table is not None:
            hits = [h for h in hits if h.get("table") == table]
        return result, hits

    def _project(self, hit: dict[str, Any], verbose: bool) -> dict[str, Any]:
        out = {k: v for k, v in hit.items() if k not in _RESERVED}
        if not verbose:
            out.pop("dimensions", None)
        return out


# Back-compat alias: the source library called this ProjectMemory.
ProjectMemory = SagJournal

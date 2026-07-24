"""Writing to the journal: append (chained) entries, crystallize + supersede facts.

`remember(...)` appends an **entry** into the append-only log and, when the chain
is enabled, links it into the tamper-evident hash chain (:mod:`sqlite3_sag.chain`).
The append is one atomic transaction:

    BEGIN IMMEDIATE            -- take the write lock BEFORE reading the chain head
      read head (seq, row_hash)
      compute this row's seq / prev_hash / row_hash
      INSERT OR IGNORE ...     -- single INSERT (fires the FTS AFTER-INSERT trigger once)
      [auto_fact: record fact in the SAME transaction]
    COMMIT

Two properties this ordering guarantees:

  - **Idempotency stays chain-safe.** ``INSERT OR IGNORE`` on a duplicate id is a
    no-op (``rowcount == 0``); the precomputed seq/hash simply evaporate, so the
    chain head is unchanged and no seq is consumed — the log stays gapless.
  - **FTS stays intact.** Exactly one INSERT per append (never INSERT-then-UPDATE),
    so the external-content FTS trigger fires once and ``rowid`` is never mutated.

`record_fact(...)` writes a durable claim (optionally superseding an older one).
Facts *mutate*, so they are NOT chained. `_record_fact_no_commit` is the variant
called inside `remember`'s transaction so the whole append commits once.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import chain as _chain
from .payload import check_payload
from .schema import JournalSchema
from .store import new_id, now_iso


def remember(
    conn: sqlite3.Connection,
    schema: JournalSchema,
    content: str,
    *,
    kind: str = "general",
    session_id: str | None = None,
    batch: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    method: str = "manual",
    id: str | None = None,
    created_at: str | None = None,
    auto_fact: bool = False,
    reason: str | None = None,
    supersedes: str | None = None,
    hash_key: Any = None,
) -> dict[str, Any]:
    """Append an entry (hash-chained when ``schema.hash_chain``). With
    ``auto_fact=True`` also crystallize it as a fact, in the same transaction.

    Returns ``{"id", "kind", "fact_id"}``, plus ``"seq"`` and ``"row_hash"`` when
    a chained row was actually inserted."""
    if not content or not content.strip():
        raise ValueError("entry content must be non-empty")
    schema.validate_kind(kind)  # register-before-emit gate
    check_payload(
        content, metadata,
        max_bytes=schema.max_content_bytes,
        refuse_secrets=schema.refuse_secrets,
    )  # refuse-to-pretend gate

    ep_id = id or new_id()
    ts = created_at or now_iso()
    tags_json = json.dumps(tags or [])
    meta_json = json.dumps(metadata or {})
    chain_on = schema.hash_chain

    conn.execute("BEGIN IMMEDIATE")
    try:
        seq: int | None = None
        prev: str | None = None
        row_hash: str | None = None
        alg: str | None = None
        if chain_on:
            head_seq, head_hash = _chain.head(conn, schema)
            seq = head_seq + 1
            prev = head_hash if head_hash is not None else _chain.genesis(schema.ns)
            alg = schema.hash_alg
            row_hash = _chain.compute_hash(
                alg, hash_key,
                _chain.preimage(
                    ns=schema.ns, seq=seq, prev=prev, id=ep_id, kind=kind,
                    content=content, session_id=session_id, batch=batch,
                    tags=tags_json, metadata=meta_json, method=method,
                    schema_version=schema.schema_version, created_at=ts,
                ),
            )

        cur = conn.execute(
            # OR IGNORE: a caller-supplied deterministic id colliding with an
            # existing row means "this exact entry was already remembered" — a
            # benign no-op that must NOT advance the chain (rowcount check below).
            f"INSERT OR IGNORE INTO {schema.episode_table} "
            "(id, content, kind, session_id, batch, tags, metadata, method, "
            " schema_version, created_at, seq, prev_hash, row_hash, hash_alg) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ep_id, content, kind, session_id, batch, tags_json, meta_json,
                method, schema.schema_version, ts, seq, prev, row_hash, alg,
            ),
        )
        inserted = cur.rowcount == 1

        fact_id: str | None = None
        if inserted and auto_fact:
            fact_id = _record_fact_no_commit(
                conn, schema, content,
                reason=reason, source_episode_id=ep_id, tags=tags,
                method="auto_fact", created_at=ts, supersedes=supersedes,
            )["id"]
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    out: dict[str, Any] = {"id": ep_id, "kind": kind, "fact_id": fact_id}
    if inserted and chain_on:
        out["seq"] = seq
        out["row_hash"] = row_hash
    return out


def _record_fact_no_commit(
    conn: sqlite3.Connection,
    schema: JournalSchema,
    claim: str,
    *,
    reason: str | None = None,
    source_episode_id: str | None = None,
    tags: list[str] | None = None,
    method: str = "manual",
    id: str | None = None,
    created_at: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Write a fact WITHOUT managing the transaction (caller holds BEGIN/COMMIT)."""
    if not claim or not claim.strip():
        raise ValueError("fact claim must be non-empty")
    fact_id = id or new_id()
    ts = created_at or now_iso()
    conn.execute(
        f"INSERT OR IGNORE INTO {schema.fact_table} "
        "(id, claim, reason, source_episode_id, tags, method, schema_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fact_id, claim, reason, source_episode_id,
            json.dumps(tags or []), method, schema.schema_version, ts, ts,
        ),
    )
    if supersedes:
        conn.execute(
            f"UPDATE {schema.fact_table} "
            "SET status = 'superseded', superseded_by = ?, updated_at = ? WHERE id = ?",
            (fact_id, ts, supersedes),
        )
    return {"id": fact_id, "supersedes": supersedes}


def record_fact(
    conn: sqlite3.Connection,
    schema: JournalSchema,
    claim: str,
    **kw: Any,
) -> dict[str, Any]:
    """Write a durable fact (its own atomic transaction). See
    :func:`_record_fact_no_commit` for kwargs. Facts are not hash-chained."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        res = _record_fact_no_commit(conn, schema, claim, **kw)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return res


def invalidate_fact(
    conn: sqlite3.Connection,
    schema: JournalSchema,
    fact_id: str,
    *,
    updated_at: str | None = None,
) -> bool:
    """Mark a fact invalidated (wrong, not merely outdated). Returns whether a
    row changed."""
    ts = updated_at or now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            f"UPDATE {schema.fact_table} SET status = 'invalidated', updated_at = ? WHERE id = ?",
            (ts, fact_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return cur.rowcount > 0

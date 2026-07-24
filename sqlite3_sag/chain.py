"""The tamper-evidence layer — a SHA-256 hash chain over the append-only log.

This is the one thing `sqlite3-sag` adds that its source (`project_memory`) did
not have: a way to *prove* the journal was not silently altered. Each chained
row carries three columns —

    seq        a 1-based monotonic sequence number (assigned under a write lock),
    prev_hash  the predecessor row's ``row_hash`` (a fixed genesis for ``seq==1``),
    row_hash   ``H(canonical_preimage(row))`` binding this row to the chain,

— and :func:`verify` walks the chain from genesis, recomputes every hash, and
reports the FIRST break it finds, classified. That is the persistence face of
*refuse-to-pretend*: a recorded event cannot be quietly changed, reordered, or
dropped without the chain saying so.

**Canonical serialization is the interop contract.** The preimage is a single
canonical-JSON object (sorted keys, compact separators, UTF-8, no ASCII
escaping) over the row's *semantic* fields. ``tags``/``metadata`` are parsed from
their stored JSON text and re-canonicalized, so no producer's JSON-formatting
quirk is baked into the hash. This is deliberately the same convention
independent producers (e.g. the SAG Video side) already use — so the *same
declared inputs produce byte-identical hashes across implementations*. The
conformance fixtures (``fixtures/``) pin exactly this.

Two honest limits, stated plainly:

  - An *unkeyed* chain proves internal self-consistency. It is only
    tamper-*evident* against an out-of-band trusted head (compare
    :func:`head_hash` to a value you stored elsewhere) — an attacker with write
    access can rewrite a row and recompute every downstream hash. The optional
    ``hmac-sha256`` mode closes that gap: without the key, downstream hashes
    cannot be recomputed.
  - The hash protects *semantic* content, not byte-exact storage: a
    whitespace-only edit to a stored JSON blob re-canonicalizes to the same
    bytes and does not trip the chain. That is the correct trade for
    cross-language interop.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

# The chain format version, folded into every preimage for domain separation.
CHAIN_VERSION = 1

# Genesis predecessor for the first row (seq == 1). A flat all-zero SHA-256 width
# so that identical logical inputs hash identically regardless of the physical
# table name ("episodes" vs "events") — cross-stream splice-protection is opt-in
# via the schema ``ns`` field, not by leaking a table name into the hash.
GENESIS = "0" * 64

# The semantic fields, in the exact set the preimage binds. Order here is
# irrelevant (``sort_keys=True`` canonicalizes), but the SET is the contract.
PREIMAGE_FIELDS = (
    "v", "ns", "seq", "prev", "id", "kind", "content",
    "session_id", "batch", "tags", "metadata",
    "method", "schema_version", "created_at",
)


def canonical_bytes(obj: Any) -> bytes:
    """The one canonical serialization: sorted keys, compact, UTF-8, no escaping."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _as_json(value: Any) -> Any:
    """Parse a stored JSON *text* column back to a value so it re-canonicalizes.

    ``tags``/``metadata`` are stored via ``json.dumps`` with Python's default
    spacing — not canonical. Parsing then letting the outer sort re-serialize is
    what makes the hash independent of the producer's JSON formatting.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def preimage(
    *,
    ns: str,
    seq: int,
    prev: str,
    id: str,
    kind: str,
    content: str,
    session_id: str | None,
    batch: str | None,
    tags: Any,
    metadata: Any,
    method: str,
    schema_version: int,
    created_at: str,
    v: int = CHAIN_VERSION,
) -> bytes:
    """Build the canonical preimage bytes for a single row.

    ``created_at`` IS bound: hashing it does not make the timestamp trustworthy
    (it is caller-injectable), it makes the *recorded* value tamper-evident and
    blocks reorder-by-rewriting-timestamps.
    """
    obj = {
        "v": v,
        "ns": ns or "",
        "seq": seq,
        "prev": prev,
        "id": id,
        "kind": kind,
        "content": content,
        "session_id": session_id,
        "batch": batch,
        "tags": _as_json(tags),
        "metadata": _as_json(metadata),
        "method": method,
        "schema_version": schema_version,
        "created_at": created_at,
    }
    return canonical_bytes(obj)


def _key_bytes(key: Any) -> bytes:
    if isinstance(key, (bytes, bytearray)):
        return bytes(key)
    if isinstance(key, str):
        return key.encode("utf-8")
    raise TypeError("hmac key must be bytes or str")


def compute_hash(alg: str | None, key: Any, data: bytes) -> str:
    """``sha256`` (default) or keyed ``hmac-sha256`` over the preimage bytes."""
    if alg in (None, "sha256"):
        return hashlib.sha256(data).hexdigest()
    if alg == "hmac-sha256":
        if key is None:
            raise ValueError("hash_alg 'hmac-sha256' requires a key (supply hash_key=)")
        return hmac.new(_key_bytes(key), data, hashlib.sha256).hexdigest()
    raise ValueError(f"unknown hash_alg {alg!r}")


def genesis(ns: str | None = "") -> str:
    """The genesis predecessor hash. ``ns`` is reserved for future per-stream
    genesis domain-separation; v1 uses a flat genesis for cross-provider parity."""
    return GENESIS


# ── the chain columns a row carries, in SELECT order used by verify ──────────
_ROW_COLS = (
    "seq", "prev_hash", "row_hash", "hash_alg", "id", "kind", "content",
    "session_id", "batch", "tags", "metadata", "method", "schema_version",
    "created_at",
)


def head(conn: Any, schema: Any) -> tuple[int, str | None]:
    """Return ``(head_seq, head_row_hash)`` of the chain, or ``(0, None)`` if empty."""
    row = conn.execute(
        f"SELECT seq, row_hash FROM {schema.episode_table} "
        f"WHERE seq IS NOT NULL ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return 0, None
    return int(row[0]), row[1]


def head_hash(conn: Any, schema: Any) -> str | None:
    """The current chain head's ``row_hash`` — checkpoint this out-of-band."""
    return head(conn, schema)[1]


def _row_preimage(schema: Any, r: dict[str, Any]) -> bytes:
    return preimage(
        ns=schema.ns,
        seq=r["seq"],
        prev=r["prev_hash"],
        id=r["id"],
        kind=r["kind"],
        content=r["content"],
        session_id=r["session_id"],
        batch=r["batch"],
        tags=r["tags"],
        metadata=r["metadata"],
        method=r["method"],
        schema_version=r["schema_version"],
        created_at=r["created_at"],
    )


def verify(conn: Any, schema: Any, *, key: Any = None) -> dict[str, Any]:
    """Walk the chain in ``seq`` order and return the FIRST break, classified.

    Returns a dict:
        ok         True iff every chained row verifies
        break      one of {"sequence-gap","predecessor-mismatch",
                   "row-hash-mismatch"} or None
        at_seq     the sequence position where the chain broke — the EXPECTED
                   seq (for a gap, the missing position) (None if ok/empty)
        at_id      the offending row's id
        expected   what verify expected (int for a gap, hex otherwise)
        found      what the row actually held
        checked    rows verified good before the break
        unchained  count of rows with seq IS NULL (legacy / chain-disabled)
        head_hash  hash of the last good row (checkpoint anchor)
        alg        the hash algorithm of the last row seen

    ``seq`` — never ``created_at`` — is the authoritative order. Unchained rows
    (``seq IS NULL``) are excluded from the walk and reported via ``unchained``.
    """
    unchained = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {schema.episode_table} WHERE seq IS NULL"
        ).fetchone()[0]
    )

    expected_seq = 1
    expected_prev = genesis(schema.ns)
    checked = 0
    last_hash: str | None = None
    last_alg: str | None = schema.hash_alg

    cur = conn.execute(
        f"SELECT {', '.join(_ROW_COLS)} FROM {schema.episode_table} "
        f"WHERE seq IS NOT NULL ORDER BY seq ASC"
    )
    for raw in cur:
        r = dict(zip(_ROW_COLS, raw))
        last_alg = r["hash_alg"]

        if r["seq"] != expected_seq:
            return _break("sequence-gap", expected_seq, r["id"], expected_seq, r["seq"], checked, unchained, last_hash, last_alg)

        if r["prev_hash"] != expected_prev:
            return _break("predecessor-mismatch", expected_seq, r["id"], expected_prev, r["prev_hash"], checked, unchained, last_hash, last_alg)

        recomputed = compute_hash(r["hash_alg"], key, _row_preimage(schema, r))
        if recomputed != r["row_hash"]:
            return _break("row-hash-mismatch", expected_seq, r["id"], recomputed, r["row_hash"], checked, unchained, last_hash, last_alg)

        expected_prev = r["row_hash"]
        last_hash = r["row_hash"]
        expected_seq += 1
        checked += 1

    return {
        "ok": True,
        "break": None,
        "at_seq": None,
        "at_id": None,
        "expected": None,
        "found": None,
        "checked": checked,
        "unchained": unchained,
        "head_hash": last_hash,
        "alg": last_alg,
    }


def _break(kind, at_seq, at_id, expected, found, checked, unchained, last_hash, last_alg):
    return {
        "ok": False,
        "break": kind,
        "at_seq": at_seq,
        "at_id": at_id,
        "expected": expected,
        "found": found,
        "checked": checked,
        "unchained": unchained,
        "head_hash": last_hash,
        "alg": last_alg,
    }

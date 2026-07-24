# 08 — API reference

Every public symbol is listed in `sqlite3_sag.__all__`
(`sqlite3_sag/__init__.py`) — 26 names. This chapter documents each,
grounded in its actual signature and source module. Nothing here is
speculative; every entry below was read from the code in this checkout.

```python
>>> import sqlite3_sag
>>> len(sqlite3_sag.__all__)
26
```

## Version markers

| symbol             | value                        | source                  |
|---------------------|-------------------------------|--------------------------|
| `__version__`        | `"0.1.0"`                     | `sqlite3_sag/__init__.py` |
| `PROTOCOL_VERSION`    | `"sag-journal/0.1-draft"`     | `sqlite3_sag/__init__.py` — the PROTOCOL.md version this build implements |

## The main object

### `SagJournal` (`sqlite3_sag/query.py`)

The object most callers use — owns a SQLite connection + a `JournalSchema`.

```python
SagJournal.open(path=":memory:", schema=None, *, dimensions=None, hash_key=None) -> SagJournal
```

Instance methods:

| method | signature | does |
|---|---|---|
| `remember` | `(content, **kw) -> dict` | append a chained entry (see `ingest.remember` for kwargs: `kind`, `session_id`, `batch`, `tags`, `metadata`, `method`, `id`, `created_at`, `auto_fact`, `reason`, `supersedes`, `hash_key`) |
| `record_fact` | `(claim, **kw) -> dict` | write a durable, unchained fact |
| `invalidate_fact` | `(fact_id, **kw) -> bool` | mark a fact invalidated; `True` iff a row changed |
| `verify` | `(*, key=None) -> dict` | walk the hash chain; see chapter 02 for the return shape |
| `head_hash` | `() -> str \| None` | current chain tip's `row_hash` |
| `recall` | `(text, *, limit=10, table=None, use_intent=True, verbose=False) -> list[dict]` | ranked hits over entries + facts; see chapter 04 |
| `recent` | `(limit=10, *, kind=None) -> list[dict]` | most recent entries, newest first, optionally filtered by `kind` |
| `count` | `() -> dict` | `{"episodes": N, "facts": M}` (`facts` counts only `status='active'`) |
| `close` | `()` | close the underlying connection |

`ProjectMemory` is an alias: `ProjectMemory = SagJournal` (back-compat; see
chapter 06).

### `open_journal(path=":memory:", schema=None, **kw) -> SagJournal`

Convenience wrapper: `return SagJournal.open(path, schema, **kw)`.

## Schema

### `JournalSchema` (`sqlite3_sag/schema.py`)

A frozen dataclass declaring kinds, table names, and the tamper-evidence /
payload policy:

```python
JournalSchema(
    kinds: tuple[str, ...] = DEFAULT_KINDS,
    episode_table: str = "episodes",
    fact_table: str = "facts",
    small_corpus_threshold: int = 100,
    schema_version: int = SCHEMA_VERSION,      # 1
    hash_chain: bool = True,
    hash_alg: str = "sha256",                  # or "hmac-sha256"
    ns: str = "",
    max_content_bytes: int = 64 * 1024,
    refuse_secrets: bool = True,
)
```

Public methods: `validate_kind(kind)` (raises `ValueError` on an undeclared
kind — chapter 03), `episode_source()` / `fact_source()` / `fact_link()` /
`corpus_schema()` (compile to `declared_core.CorpusSchema` — chapter 04).

`MemorySchema` is an alias: `MemorySchema = JournalSchema` (back-compat).

### `DEFAULT_KINDS: tuple[str, ...]`

```python
("decision", "gotcha", "insight", "invariant", "task", "milestone", "general")
```

### `FACT_STATUSES: tuple[str, ...]`

```python
("active", "superseded", "invalidated")
```

The fixed lifecycle a fact's `status` column moves through.

### `SCHEMA_VERSION: int` — `1`. Stamped onto every row's `schema_version` column.

## Writing (functional form)

The same operations `SagJournal` wraps, callable directly against a
connection + schema — used internally by `SagJournal` and available for
callers who manage their own connection lifecycle.

### `remember(conn, schema, content, *, kind="general", session_id=None, batch=None, tags=None, metadata=None, method="manual", id=None, created_at=None, auto_fact=False, reason=None, supersedes=None, hash_key=None) -> dict`

(`sqlite3_sag/ingest.py`) One atomic transaction: `BEGIN IMMEDIATE` → read
chain head → compute `seq`/`prev_hash`/`row_hash` → single `INSERT OR
IGNORE` → optional same-transaction fact → `COMMIT`. Returns `{"id", "kind",
"fact_id"}`, plus `"seq"`/`"row_hash"` when a chained row was actually
inserted (absent on a duplicate-`id` no-op).

### `record_fact(conn, schema, claim, **kw) -> dict`

Write a durable fact in its own transaction. Facts are **not** hash-chained
(they mutate via supersede/invalidate; the chain only covers the append-only
entry log). `**kw`: `reason`, `source_episode_id`, `tags`, `method`, `id`,
`created_at`, `supersedes` (an existing fact id to mark `superseded`).

### `invalidate_fact(conn, schema, fact_id, *, updated_at=None) -> bool`

Mark a fact `status='invalidated'` (wrong, not merely outdated). Returns
whether a row actually changed.

## Tamper-evidence (`sqlite3_sag/chain.py`)

| symbol | signature | does |
|---|---|---|
| `verify` | `(conn, schema, *, key=None) -> dict` | walk the chain from genesis; return the first break, classified (chapter 02) |
| `head_hash` | `(conn, schema) -> str \| None` | the current chain tip's `row_hash` |
| `compute_hash` | `(alg, key, data: bytes) -> str` | `sha256` (default) or keyed `hmac-sha256` over preimage bytes |
| `preimage` | `(*, ns, seq, prev, id, kind, content, session_id, batch, tags, metadata, method, schema_version, created_at, v=CHAIN_VERSION) -> bytes` | build the canonical preimage bytes for one row |
| `canonical_bytes` | `(obj) -> bytes` | `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` — the one canonical serialization |
| `genesis` | `(ns: str \| None = "") -> str` | the genesis predecessor hash (always `GENESIS`; `ns` reserved for future per-stream domain separation) |
| `GENESIS` | `"0" * 64` | the flat all-zero predecessor for `seq == 1` |
| `CHAIN_VERSION` | `1` | folded into every preimage for domain separation |

## Payload gate (`sqlite3_sag/payload.py`)

### `check_payload(content, metadata=None, *, max_bytes=64*1024, refuse_secrets=True) -> None`

Raises `InadmissiblePayload` (a `ValueError` subclass) if the payload may not
enter the journal — size cap, secret markers, or a disallowed
metadata type (chapter 03). Returns `None` on success (no return value to
check — the absence of an exception *is* the pass).

### `InadmissiblePayload(ValueError)`

The exception type raised by `check_payload` (and therefore by `remember()`
when the gate trips).

## Store (`sqlite3_sag/store.py`)

| symbol | signature | does |
|---|---|---|
| `connect` | `(path=":memory:", *, busy_timeout_ms=5000) -> sqlite3.Connection` | a connection tuned for a chained append-only journal: manual transactions (`isolation_level=None`), `foreign_keys=ON`, `busy_timeout`, WAL for file DBs |
| `new_id` | `() -> str` | a fresh opaque id (`uuid.uuid4().hex`) |
| `now_iso` | `() -> str` | current UTC timestamp, ISO-8601 |

## Not in `__all__` but worth knowing

`sqlite3_sag.conformance` (`run_fixture`, `check_fixture`, `RunResult`) is a
public module, importable as `from sqlite3_sag.conformance import
check_fixture` — it's the fixture-conformance harness (chapter 05), not part
of the day-to-day journal API, so it isn't re-exported at the top level.
`sqlite3_sag.store.create_store` (build the tables + install FTS; called
internally by `SagJournal.__init__`) is likewise not top-level — most callers
never need it directly since `SagJournal.open` calls it for you.

## Verify your build

```bash
python3 -c "import sqlite3_sag; print(len(sqlite3_sag.__all__)); print(sorted(sqlite3_sag.__all__))"
# 26
# ['CHAIN_VERSION', 'DEFAULT_KINDS', 'FACT_STATUSES', 'GENESIS', ...]

python3 -c "
import sqlite3_sag as s
assert all(hasattr(s, name) for name in s.__all__)
print('every __all__ symbol resolves: ok')
"
```

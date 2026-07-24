# 06 — Compat: the project_memory shim, and honest migration

`sqlite3-sag` is the successor to `project_memory`'s journal core. This
chapter covers the two compat surfaces: the `project_memory` shim package
(so existing callers need not change a line), and what happens when you open
a database that predates the hash chain. Both are exercised in
`examples/compat_shim_migration.py`.

## The alias names

`sqlite3_sag/schema.py` and `sqlite3_sag/query.py` define the primitive's
real names, then alias the source library's names onto them:

```python
# sqlite3_sag/schema.py
MemorySchema = JournalSchema

# sqlite3_sag/query.py
ProjectMemory = SagJournal
```

These are `is`-identical, not "compatible copies":

```python
from project_memory import MemorySchema, ProjectMemory
import sqlite3_sag

assert MemorySchema is sqlite3_sag.JournalSchema
assert ProjectMemory is sqlite3_sag.SagJournal
```

## The project_memory shim package

`project_memory/__init__.py` is a small top-level package whose entire body
is re-exports from `sqlite3_sag`:

```python
from sqlite3_sag import (
    DEFAULT_KINDS, FACT_STATUSES, SCHEMA_VERSION, InadmissiblePayload,
    JournalSchema, MemorySchema, ProjectMemory, SagJournal, check_payload,
    connect, invalidate_fact, record_fact, remember, verify,
)
```

So code written as `from project_memory import DEFAULT_KINDS, MemorySchema,
ProjectMemory` runs **unchanged** against `sqlite3_sag`. This is deliberate:
the shim exists so the two consumers this journal was extracted *from*
(`declared_grep`'s and `declared_context`'s receipt-journaling calls) don't
need a rewrite. `tests/test_sqlite3_sag.py::test_consumer_pattern_*` pin the
exact call shape of both consumers as regression tests.

The shim re-exports the **journal surface only** — append, recall, verify.
It does *not* re-export the fuller `project_memory` library's natural-language
*ask* layer, the synthesis-mud epistemic guard, dense embeddings, or the
portfolio brain — those stay out of scope for this primitive and live in the
original package.

**Do not co-install this shim alongside the original `project_memory`
distribution.** The top-level package name collides *by design* — this is
declared the successor, not a fork living alongside the original.

## Migrating an old database — and its honest limit

A database written before `sqlite3-sag` existed has no `seq` / `prev_hash` /
`row_hash` / `hash_alg` columns at all. Opening it with `SagJournal.open` (or
`ProjectMemory.open` through the shim) migrates those columns **in place**:

```python
# sqlite3_sag/store.py::_migrate_chain_columns
have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
for col, decl in _CHAIN_COLUMNS:
    if col not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
```

Pre-existing rows are left `seq IS NULL` — honestly **unchained**. Only new
appends, from that point forward, are chained:

```python
j = ProjectMemory.open("old.db", MemorySchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))
j.verify()
# {'ok': True, 'checked': 0, 'unchained': 1, 'head_hash': None, ...}  -- the legacy row

j.remember("a decision made after migrating to sqlite3-sag", kind="decision")
j.verify()
# {'ok': True, 'checked': 1, 'unchained': 1, ...}  -- new chain, starting fresh from GENESIS
```

**Why there is no backfill.** `sqlite3-sag` could, in principle, compute a
retroactive chain over the pre-existing rows in `created_at` order. It
deliberately does not, by default (PROTOCOL.md §11):

> Backfilling a chain over pre-existing rows is available but must be
> labeled honestly: a retroactive chain cannot prove the past — it only
> establishes a notarization point from backfill-time forward, and only if
> the resulting head_hash is checkpointed out-of-band. The reference default
> does not backfill (it will not fake tamper-evidence).

A backfilled hash over rows nobody watched being written proves nothing
about whether *those* rows were altered before the backfill ran — it would
only look like proof. `unchained` in every `verify()` result is the honest
signal: "this many rows predate any tamper-evidence; don't trust the chain
for them."

## Verify your build

```bash
python examples/compat_shim_migration.py
#   MemorySchema is sqlite3_sag.JournalSchema, ProjectMemory is sqlite3_sag.SagJournal
#   the declared-grep consumer pattern runs unchanged through the shim
#   pre-existing row is honestly unchained: verify() -> {'ok': True, ..., 'unchained': 1}
#   new append is chained from genesis: seq=1, verify() -> checked=1, unchained=1
# Verify your build: ok

pytest -q -k "consumer_pattern or old_db"
```

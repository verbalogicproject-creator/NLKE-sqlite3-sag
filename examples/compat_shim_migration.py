"""The project_memory compat shim, and an honest old-database migration.

Two things this example proves:

  1. ``from project_memory import MemorySchema, ProjectMemory`` is not a
     re-implementation -- the shim re-exports the SAME classes as
     ``sqlite3_sag.JournalSchema`` / ``sqlite3_sag.SagJournal`` (``is``, not
     just "compatible").
  2. Opening a pre-chain database (created before sqlite3-sag existed) adds
     the chain columns IN PLACE and leaves old rows honestly ``unchained``
     (``seq IS NULL``) -- it does NOT backfill a fake chain over history it
     cannot prove (see PROTOCOL.md §11).

Run:  python examples/compat_shim_migration.py
Ends with "Verify your build: ok".
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3_sag
from project_memory import DEFAULT_KINDS, MemorySchema, ProjectMemory

# ── 1. the shim's names ARE sqlite3_sag's names, not copies ─────────────────
assert MemorySchema is sqlite3_sag.JournalSchema
assert ProjectMemory is sqlite3_sag.SagJournal
print("  MemorySchema is sqlite3_sag.JournalSchema, ProjectMemory is sqlite3_sag.SagJournal")

# The two shipped consumers' exact call shape runs unchanged through the shim.
schema = MemorySchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"))
mem = ProjectMemory.open(":memory:", schema)
res = mem.remember(
    "retrieval 'auth flow' -> src/login.py [bm25] score=0.0313",
    kind="sag.retrieval", tags=["declared-grep", "retrieval", "bm25"],
)
assert res["kind"] == "sag.retrieval" and mem.verify()["ok"]
print("  the declared-grep consumer pattern runs unchanged through the shim")

# ── 2. old-database migration: pre-chain rows stay honestly unchained ───────
_OLD_DDL = """
CREATE TABLE episodes (
  id TEXT PRIMARY KEY, content TEXT NOT NULL, kind TEXT NOT NULL,
  session_id TEXT, batch TEXT, tags TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}',
  method TEXT DEFAULT 'manual', schema_version INTEGER DEFAULT 1, created_at TEXT NOT NULL
)"""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "old.db"

        # Simulate a database written by a pre-chain producer: no seq/prev_hash/
        # row_hash/hash_alg columns exist at all.
        raw = sqlite3.connect(db)
        raw.execute(_OLD_DDL)
        raw.execute(
            "INSERT INTO episodes (id, content, kind, created_at) VALUES (?,?,?,?)",
            ("legacy-1", "a decision made before the chain existed", "decision",
             "2025-06-01T00:00:00+00:00"),
        )
        raw.commit()
        raw.close()

        # Opening it in-place migrates the chain columns (ALTER TABLE ADD COLUMN,
        # default NULL) -- see sqlite3_sag/store.py::_migrate_chain_columns.
        j = ProjectMemory.open(str(db), MemorySchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))

        v0 = j.verify()
        assert v0["ok"] and v0["checked"] == 0 and v0["unchained"] == 1, v0
        print(f"  pre-existing row is honestly unchained: verify() -> {v0}")

        # A NEW append starts a fresh chain from genesis -- it does not pretend
        # to extend a chain the legacy row never had.
        r = j.remember("a decision made after migrating to sqlite3-sag", kind="decision")
        v1 = j.verify()
        assert v1["ok"] and v1["checked"] == 1 and v1["unchained"] == 1 and r["seq"] == 1, v1
        print(f"  new append is chained from genesis: seq={r['seq']}, verify() -> checked=1, unchained=1")
        assert j.count()["episodes"] == 2
        j.close()

    print("Verify your build: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

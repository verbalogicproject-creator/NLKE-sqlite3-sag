"""Physical storage: build the ``episodes`` + ``facts`` tables from a
`JournalSchema`, add the hash-chain columns, then let `declared_core` attach its
FTS index + sync triggers.

`sqlite3-sag` brings the base tables + the tamper-evidence columns
(``seq``/``prev_hash``/``row_hash``/``hash_alg``); `declared_core` owns the
search layer. The chain columns are **additive and default NULL**, so a row
written by any path that doesn't chain still inserts cleanly, and an *old*
database created before the chain existed is migrated in place (``ALTER TABLE
ADD COLUMN``) with its pre-existing rows left unchained.

Transaction discipline: the connection runs in manual mode
(``isolation_level=None``) so the append path can take an explicit
``BEGIN IMMEDIATE`` write lock before reading the chain head — the
read-modify-write that assigns ``seq`` must be serialized across writers.
``PRAGMA busy_timeout`` makes concurrent writers block-and-retry under WAL
instead of erroring.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from declared_core import CorpusSchema, install_fts

from .schema import JournalSchema

_CHAIN_COLUMNS = (
    ("seq", "INTEGER"),
    ("prev_hash", "TEXT"),
    ("row_hash", "TEXT"),
    ("hash_alg", "TEXT"),
)


def connect(path: str = ":memory:", *, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Open a SQLite connection tuned for a chained append-only journal.

    - ``isolation_level=None`` → manual transactions (explicit BEGIN IMMEDIATE).
    - ``foreign_keys=ON`` for the entry→fact referential link.
    - ``busy_timeout`` so concurrent writers block-and-retry under WAL.
    - WAL journal mode for file DBs (non-blocking readers).
    """
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def new_id() -> str:
    """A fresh opaque id. Callers may pass their own for deterministic seeds."""
    return uuid.uuid4().hex


def now_iso() -> str:
    """UTC timestamp in ISO-8601. Callers may pass their own for deterministic seeds."""
    return datetime.now(timezone.utc).isoformat()


def _episodes_ddl(schema: JournalSchema) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {schema.episode_table} (
  id             TEXT PRIMARY KEY,
  content        TEXT NOT NULL,
  kind           TEXT NOT NULL,
  session_id     TEXT,
  batch          TEXT,
  tags           TEXT DEFAULT '[]',
  metadata       TEXT DEFAULT '{{}}',
  method         TEXT DEFAULT 'manual',
  schema_version INTEGER DEFAULT {schema.schema_version},
  created_at     TEXT NOT NULL,
  seq            INTEGER,
  prev_hash      TEXT,
  row_hash       TEXT,
  hash_alg       TEXT
)"""


def _facts_ddl(schema: JournalSchema) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {schema.fact_table} (
  id                TEXT PRIMARY KEY,
  claim             TEXT NOT NULL,
  reason            TEXT,
  source_episode_id TEXT REFERENCES {schema.episode_table}(id),
  status            TEXT DEFAULT 'active' CHECK(status IN ('active', 'superseded', 'invalidated')),
  superseded_by     TEXT REFERENCES {schema.fact_table}(id),
  tags              TEXT DEFAULT '[]',
  method            TEXT DEFAULT 'manual',
  schema_version    INTEGER DEFAULT {schema.schema_version},
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
)"""


def _migrate_chain_columns(conn: sqlite3.Connection, table: str) -> None:
    """Add any missing chain columns to a pre-existing table (old-DB compat).

    New tables already have them (in the DDL), so this is a no-op there. Old
    rows stay ``seq IS NULL`` (unchained); only new appends are chained. We do
    NOT backfill — a retroactive chain cannot prove the past, and faking it would
    be dishonest (see PROTOCOL.md §Migration)."""
    have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, decl in _CHAIN_COLUMNS:
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def create_store(
    conn: sqlite3.Connection,
    schema: JournalSchema,
    *,
    dimensions: object | None = None,
) -> CorpusSchema:
    """Create the entries + facts tables (if absent), migrate the chain columns,
    install FTS over both. Returns the compiled `declared_core.CorpusSchema`.
    Idempotent: safe to call on every connect."""
    ep, ft = schema.episode_table, schema.fact_table
    conn.execute(_episodes_ddl(schema))
    conn.execute(_facts_ddl(schema))
    _migrate_chain_columns(conn, ep)  # old-DB in-place migration
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ep}_kind ON {ep}(kind)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ep}_batch ON {ep}(batch)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ep}_created ON {ep}(created_at)")
    # A duplicate non-NULL seq is a hard error (belt-and-suspenders); many NULL
    # seqs coexist (NULLs are distinct in SQLite) so compat mode is unaffected.
    conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{ep}_seq ON {ep}(seq) WHERE seq IS NOT NULL")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ep}_seq ON {ep}(seq)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ft}_status ON {ft}(status)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ft}_created ON {ft}(created_at)")
    corpus = schema.corpus_schema(dimensions=dimensions)
    install_fts(conn, corpus)
    return corpus

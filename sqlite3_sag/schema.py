"""JournalSchema — declare how a project's journal becomes a searchable,
chained corpus.

`sqlite3-sag` stores two kinds of thing (inherited from its source,
`project_memory`):

  - **entries** (the ``episodes`` table by default) — an append-only, now
    *hash-chained* log of what happened. Keyed by a stable id, tagged, grouped by
    ``kind`` (decision / gotcha / …), and — new here — linked into a tamper-
    evident chain (see :mod:`sqlite3_sag.chain`).
  - **facts** — durable claims crystallized from entries, with a supersession
    chain. Facts *mutate* (supersede / invalidate), so they are deliberately
    **out of the hash chain**; only the append-only entry log is chained.

A `JournalSchema` *declares* these two tables and compiles to a
`declared_core.CorpusSchema` — so recall rides the same declared engine every
repo in this family uses (BM25 + structural expansion + RRF, dense optional).

The register-before-emit gate (:meth:`validate_kind`) is the journal's signature
discipline: an undeclared ``kind`` raises rather than being silently mis-recorded.

    from sqlite3_sag import JournalSchema, DEFAULT_KINDS
    schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"))

Chain knobs (all default to a safe, on-by-default floor):
    hash_chain   append rows into the tamper-evident chain (default True)
    hash_alg     "sha256" (default) or "hmac-sha256" (keyed; supply hash_key= at open)
    ns           logical stream namespace, bound into the hash for cross-stream
                 splice-protection (default ""; e.g. set to a project id)
    max_content_bytes / refuse_secrets   the payload-admissibility gate knobs
"""

from __future__ import annotations

from dataclasses import dataclass

from declared_core import CorpusSchema, Link, SourceTable

# The generic default entry taxonomy. Domain-neutral — override ``kinds=`` with
# whatever vocabulary your project (or SAG kind, e.g. "sag.retrieval") uses.
DEFAULT_KINDS: tuple[str, ...] = (
    "decision",
    "gotcha",
    "insight",
    "invariant",
    "task",
    "milestone",
    "general",
)

# Facts move through a small, fixed lifecycle (drives the ``where`` filter + the
# supersession chain). Structural, not a user taxonomy.
FACT_STATUSES: tuple[str, ...] = ("active", "superseded", "invalidated")

# On-disk schema version, stamped onto every row.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class JournalSchema:
    """A full declaration: how a project's entries + facts map to two tables,
    plus the tamper-evidence policy for the append-only entry log."""

    kinds: tuple[str, ...] = DEFAULT_KINDS
    episode_table: str = "episodes"
    fact_table: str = "facts"
    small_corpus_threshold: int = 100
    schema_version: int = SCHEMA_VERSION
    # ── tamper-evidence policy ───────────────────────────────────────────────
    hash_chain: bool = True
    hash_alg: str = "sha256"
    ns: str = ""
    # ── payload-admissibility policy ─────────────────────────────────────────
    max_content_bytes: int = 64 * 1024
    refuse_secrets: bool = True

    def __post_init__(self) -> None:
        if not self.kinds:
            raise ValueError("JournalSchema needs at least one entry kind")
        if len(self.kinds) != len(set(self.kinds)):
            raise ValueError(f"duplicate entry kinds: {self.kinds}")
        if self.episode_table == self.fact_table:
            raise ValueError("episode_table and fact_table must differ")
        if self.hash_alg not in ("sha256", "hmac-sha256"):
            raise ValueError(f"unknown hash_alg {self.hash_alg!r}")

    # ── register-before-emit gate ────────────────────────────────────────────
    def validate_kind(self, kind: str) -> None:
        if kind not in self.kinds:
            raise ValueError(
                f"unknown entry kind {kind!r}; declared kinds are "
                f"{sorted(self.kinds)}. Add it to JournalSchema(kinds=...)."
            )

    # ── compile to the declared_core engine ──────────────────────────────────
    def episode_source(self) -> SourceTable:
        return SourceTable(
            name=self.episode_table,
            id_column="id",
            text_columns=("content",),
            carry_columns=("session_id", "created_at"),
            cluster_columns=("kind", "batch"),
            tag_columns=("tags",),
            order_by="created_at DESC",
        )

    def fact_source(self) -> SourceTable:
        return SourceTable(
            name=self.fact_table,
            id_column="id",
            text_columns=("claim", "reason"),
            carry_columns=("source_episode_id", "status", "created_at"),
            tag_columns=("tags",),
            where="status = 'active'",
            order_by="created_at DESC",
        )

    def fact_link(self) -> Link:
        return Link(child=self.fact_table, parent=self.episode_table, key="source_episode_id")

    def corpus_schema(self, *, dimensions: object | None = None) -> CorpusSchema:
        return CorpusSchema(
            sources=(self.episode_source(), self.fact_source()),
            links=(self.fact_link(),),
            dimensions=dimensions,
            small_corpus_threshold=self.small_corpus_threshold,
        )


# Back-compat alias: the source library called this MemorySchema. Code written
# as `from project_memory import MemorySchema` keeps working (via the compat shim).
MemorySchema = JournalSchema

# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to the versioning implied by `PROTOCOL_VERSION`
(`sag-journal/0.1-draft`) for the wire contract, and `__version__` /
`pyproject.toml`'s `version` for the package itself.

## [Unreleased]

Nothing yet. See `ROADMAP.md` for planned work (a dense-recall booster
wired into `SagJournal.recall()`, a `sqlite-vec`-style C loadable extension,
and the joint fixture freeze with the SAG Video side for `PROTOCOL.md`
`0.1`).

## [0.1.0] — initial release

### Added

- **`SagJournal`** (`sqlite3_sag.SagJournal`) — the core object: `open`,
  `remember`, `record_fact`, `invalidate_fact`, `verify`, `head_hash`,
  `recall`, `recent`, `count`, `close`.
- **The SHA-256 hash chain** (`sqlite3_sag.chain`) — `seq` / `prev_hash` /
  `row_hash` / `hash_alg` columns on the append-only `episodes` table; a
  canonical-JSON preimage (`PROTOCOL.md` §5.1) that hashes identically
  across producers; `verify()` walking the chain from genesis and
  classifying the first break as `sequence-gap`, `predecessor-mismatch`, or
  `row-hash-mismatch`. Optional `hmac-sha256` keyed mode for an
  out-of-band-secret adversarial setting.
- **Register-before-emit** (`JournalSchema.validate_kind`) — an undeclared
  entry `kind` raises `ValueError` rather than being silently recorded.
- **Refuse-to-pretend** (`sqlite3_sag.payload.check_payload`) — a payload-
  admissibility gate refusing oversize content (default 64 KiB cap),
  credential markers (PEM private-key headers, AWS access-key ids), and
  floats/raw-bytes in `metadata`.
- **Idempotent, chain-safe append** (`sqlite3_sag.ingest.remember`) — one
  atomic transaction (`BEGIN IMMEDIATE` → compute chain fields → single
  `INSERT OR IGNORE` → `COMMIT`); a duplicate `id` is a true no-op that does
  not advance `seq` or the chain head.
- **BM25 + structural recall over the journal itself**
  (`SagJournal.recall`), via the vendored `declared_core` engine: lexical
  search (FTS5), structural expansion (shared `kind`/`tags`, the
  fact→episode link), a deterministic 12-dimension rules scorer, and
  intent-adaptive reciprocal-rank fusion. Dense (embedding) recall exists in
  `declared_core` but is not wired into `SagJournal.recall()` in this
  release (`dense=None` is hardcoded) — see `ROADMAP.md`.
- **Old-database migration** (`sqlite3_sag.store._migrate_chain_columns`) —
  opening a pre-chain database adds the chain columns in place
  (`ALTER TABLE ADD COLUMN`); pre-existing rows are left honestly
  `unchained` (`seq IS NULL`); no backfill by default (`PROTOCOL.md` §11).
- **`PROTOCOL.md`** (`sag-journal/0.1-draft`) — the versioned, provider-
  neutral journal protocol: entry shape, the hash-chain algorithm,
  idempotency/revision, receipts/observations/claims/trust as declared
  kinds, committed-vs-observed, `verify()`'s contract, migration, and open
  reconciliation items pending joint agreement with the SAG Video side.
- **Conformance fixtures** (`fixtures/*.json` + `sqlite3_sag.conformance`) —
  four fixtures (`basic_two_rows`, `idempotent_reinsert`, `tamper_content`,
  `sequence_gap`) pinning exact chained-row hashes and `verify()` outcomes,
  reproducible by any adapter, in any language.
- **`project_memory` compat shim** — `MemorySchema`/`ProjectMemory` alias
  `JournalSchema`/`SagJournal` exactly (`is`-identical), so code written
  against `project_memory`'s journal surface runs unchanged.
- **CLI** (`sqlite3-sag` / `python -m sqlite3_sag`) — `append`, `verify`
  (exits non-zero on a broken chain), `recent`.
- **Vendored `declared_core`** — a byte-identical, drift-guarded in-repo
  copy (`VENDORED.json`, `tools/revendor.py`) so the package installs and
  runs standalone with zero PyPI/PYTHONPATH coupling to a sibling repo.
- **21 tests** (`tests/`): extraction parity, chain monotonicity, all three
  tamper-break classes, idempotency, chain-disabled degradation, the payload
  gate, `hmac-sha256` mode, old-database migration, and conformance-fixture
  reproduction.

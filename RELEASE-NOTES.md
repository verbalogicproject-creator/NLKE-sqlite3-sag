# Release notes

## v0.1.0 — initial release

`sqlite3-sag` is the SAG journal as a tamper-evident, SQLite-native
primitive: a declared, append-only log of typed entries with a SHA-256 hash
chain you can `verify()`. It is extracted and generalized from
`project_memory`'s journal core, given the tamper-evidence that source never
had, pure-Python and pure-stdlib.

### Headline capability: verifiable journaling, $0

```python
from sqlite3_sag import SagJournal, JournalSchema, DEFAULT_KINDS

j = SagJournal.open("journal.db", JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))
j.remember("retrieval 'auth flow' -> src/login.py [bm25]", kind="sag.retrieval")
j.verify()   # {'ok': True, 'checked': 1, 'head_hash': '<64-hex>', ...}

j.conn.execute("UPDATE episodes SET content='forged' WHERE seq=1")
j.verify()["break"]   # 'row-hash-mismatch'
```

No SQLite loadable extension, no numpy, no network, no API key, zero
required runtime dependencies (`pyproject.toml`: `dependencies = []`). Every
runtime import in `sqlite3_sag/` is stdlib: `hashlib`, `hmac`, `json`,
`sqlite3`, `uuid`, `datetime`, `argparse`, `re`. Verified by
`tools/verify_standalone.sh`'s "$0 floor" check, which installs the wheel
into a fresh venv, uninstalls numpy if present, and re-runs append + verify
+ recall.

### What ships in this release

- The hash chain: `seq`/`prev_hash`/`row_hash`/`hash_alg`, canonical-JSON
  preimage, `verify()` classifying `sequence-gap` /
  `predecessor-mismatch` / `row-hash-mismatch`, and an optional
  `hmac-sha256` keyed mode for an adversarial write-access threat model.
- Register-before-emit (undeclared `kind` raises) and refuse-to-pretend
  (oversize content / credential markers / float metadata raise
  `InadmissiblePayload`) — both fail loud, both run before a row touches
  the chain.
- BM25 + structural recall over the journal itself, riding the vendored
  `declared_core` engine — no embeddings required for useful recall.
- `PROTOCOL.md` (`sag-journal/0.1-draft`) and four conformance fixtures
  (`fixtures/*.json`) — the cross-provider hash-parity contract this
  release commits to, and the concrete answer to the X1-CLAUDE-002
  cross-provider delegation request (see
  `docs/05-conformance-and-provider-neutrality.md`).
- A `project_memory` compat shim — `MemorySchema`/`ProjectMemory` alias
  `JournalSchema`/`SagJournal` exactly, so the two consumers this journal
  was extracted from (`declared_grep`, `declared_context`) run unchanged.
- A minimal CLI (`sqlite3-sag append|verify|recent`) that drops `verify`
  into CI with a real non-zero exit code on a broken chain.
- 21 passing tests, 4 conformance fixtures, and a standalone-install proof
  (`tools/verify_standalone.sh`) exercised in a fresh venv with the
  canonical sibling package provably absent.

### Known limits, stated honestly (not deferred silently)

- **Dense (semantic) recall is not wired into `SagJournal.recall()`.**
  `declared_core` supports it (`NumpyVectorIndex`), but the journal's own
  `_run()` hardcodes `dense=None`. See `ROADMAP.md`.
- **No SQL-native (C loadable-extension) form.** This release is the
  pure-Python protocol + reference library; a `sqlite-vec`-style extension
  is future work.
- **Old-database migration does not backfill a chain over pre-existing
  rows.** By design (`PROTOCOL.md` §11) — a retroactive chain cannot prove
  the past, and this release will not fake tamper-evidence.
- **`PROTOCOL.md` is `0.1-draft`, not frozen.** §13 lists four open
  reconciliation items (Unicode normalization, the metadata number profile,
  `ns`↔scope mapping, receipt/observation field-name alignment) that must
  be agreed jointly with the SAG Video side before a `0.1` freeze.

### Upgrading from `project_memory`

No code changes required for the journal surface — see
`docs/06-compat.md`. Do not co-install this package's `project_memory` shim
alongside the original `project_memory` distribution; the top-level package
name collides by design (this is the declared successor).

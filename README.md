# sqlite3-sag

[![CI](https://github.com/verbalogicproject-creator/NLKE-sqlite3-sag/actions/workflows/ci.yml/badge.svg)](https://github.com/verbalogicproject-creator/NLKE-sqlite3-sag/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**The SAG journal as a tamper-evident, SQLite-native primitive.** A declared,
append-only log of typed entries with a **SHA-256 hash chain you can verify** — so a
recorded event cannot be silently altered, reordered, or dropped without the journal
saying so. It is the *persistence face* of **refuse-to-pretend / committed-vs-observed**,
the same discipline the retrieval side of this family (declared-grep / declared-context)
already ships.

- **$0, local-first, offline.** Pure-Python, pure-stdlib. **No SQLite loadable extension**
  (stdlib `sqlite3` frequently can't load one), no numpy, no network on the default path.
- **Register-before-emit.** An undeclared entry `kind` is refused, not silently recorded.
- **Verifiable.** `verify()` walks the chain from genesis and reports the first break,
  classified (`sequence-gap` / `predecessor-mismatch` / `row-hash-mismatch`).
- **Provider-neutral.** A versioned [journal **protocol**](PROTOCOL.md) + cross-provider
  [conformance **fixtures**](fixtures/): identical declared inputs hash byte-identically
  across implementations, so another producer (in any language/store) can adopt it via an
  adapter.

Extracted and generalized from `project_memory`'s journal core, given the tamper-evidence
it did not have.

## Install

```bash
pip install -e ".[dev]"     # from a checkout; runtime deps are zero
```

## 60-second quickstart

```python
from sqlite3_sag import SagJournal, JournalSchema, DEFAULT_KINDS

# declare your kinds up front (register-before-emit)
schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"))
j = SagJournal.open("journal.db", schema)

j.remember("retrieval 'auth flow' -> src/login.py [bm25] score=0.031",
           kind="sag.retrieval", tags=["declared-grep", "bm25"])
j.remember("retrieval 'signup' -> src/signup.py [bm25] score=0.028",
           kind="sag.retrieval", tags=["declared-grep", "bm25"])

print(j.verify())
# {'ok': True, 'break': None, 'at_seq': None, 'at_id': None, 'expected': None,
#  'found': None, 'checked': 2, 'unchained': 0, 'head_hash': '<64-hex-chars>', 'alg': 'sha256'}

print(j.recall("auth"))
# [{'table': 'episodes', 'id': '...', 'content': "retrieval 'auth flow' -> ...",
#   'kind': 'sag.retrieval', 'rrf_score': 0.027, 'rrf_sources': ['bm25', ...], ...}, ...]

# tamper detection
j.conn.execute("UPDATE episodes SET content='forged' WHERE seq=1")
print(j.verify()["break"])   # 'row-hash-mismatch'
```

CLI:

```bash
sqlite3-sag append journal.db "a decision" --kind decision
# {"id": "...", "kind": "decision", "fact_id": null, "seq": 1, "row_hash": "..."}

sqlite3-sag verify journal.db        # exits non-zero if the chain is broken
# { "ok": true, "break": null, ..., "checked": 1, "unchained": 0, "head_hash": "...", "alg": "sha256" }

sqlite3-sag recent journal.db
# {"id": "...", "content": "a decision", "kind": "decision", "batch": null, "tags": [], "created_at": "...", "seq": 1}
```

## Verify your build

```bash
pytest -q                          # the Stage-1 green bar: 25 passed (chain, tamper, idempotency, conformance, compat, hmac, migration)
python tools/gen_fixtures.py       # regenerate fixtures (should be a no-op on a clean tree)
python examples/append_and_verify.py   # prints "Verify your build: ok"
python tools/revendor.py check     # vendoring drift guard for declared_core/
bash tools/verify_standalone.sh    # fresh-venv install + $0-floor (no numpy) + full suite, standalone
```

## How it fits together

Read bottom-up: SQLite is the substrate, `declared_core` is a vendored,
drift-guarded copy providing the search math, and `sqlite3_sag` is the
primitive itself — three small modules doing the write path, one facade
object most callers touch.

```
┌──────────────────────────────────────────────────────────────────┐
│  your code:  SagJournal.remember() / .recall() / .verify()        │
├──────────────────────────────────────────────────────────────────┤
│  sqlite3_sag/query.py     SagJournal -- the journal facade         │
├───────────────────┬────────────────────┬───────────────────────────┤
│ ingest.py          │ chain.py            │ payload.py                │
│ atomic append tx    │ hash chain           │ refuse-to-pretend gate    │
│ (BEGIN IMMEDIATE,   │ seq/prev_hash/       │ size cap, secret markers, │
│  single INSERT)     │ row_hash, verify()   │ float/bytes ban           │
├───────────────────┴────────────────────┴───────────────────────────┤
│  sqlite3_sag/schema.py    JournalSchema -- kinds + tables + hash policy │
├──────────────────────────────────────────────────────────────────┤
│  sqlite3_sag/store.py     connect() + DDL + old-DB migration       │
├──────────────────────────────────────────────────────────────────┤
│  declared_core (vendored)  BM25 + structural expansion + RRF + dims│
├──────────────────────────────────────────────────────────────────┤
│  SQLite (stdlib sqlite3)   episodes + facts tables, FTS5 index     │
└──────────────────────────────────────────────────────────────────┘
```

`PROTOCOL.md` sits alongside all of this as the versioned wire contract; the
`fixtures/` directory pins it in a form any independent adapter can
reproduce — see `docs/05-conformance-and-provider-neutrality.md`.

## What you get

- A `SagJournal` object: `remember()`, `record_fact()`, `verify()`,
  `head_hash()`, `recall()`, `recent()`, `count()`.
- A SHA-256 hash chain over every appended entry, with `verify()` reporting
  the first break, classified (`sequence-gap` / `predecessor-mismatch` /
  `row-hash-mismatch`), plus an optional `hmac-sha256` keyed mode.
- Two write-time gates that fail loud: register-before-emit (undeclared
  `kind` raises) and refuse-to-pretend (oversize content / credential
  markers / floats-in-metadata raise `InadmissiblePayload`).
- BM25 + structural recall over your own journal — no embeddings required.
- `PROTOCOL.md`, a versioned, provider-neutral journal protocol, and four
  conformance fixtures any independent adapter can reproduce byte-for-byte.
- A `project_memory` compat shim (`MemorySchema`/`ProjectMemory` are the
  exact same classes as `JournalSchema`/`SagJournal`).
- A minimal CLI (`sqlite3-sag append|verify|recent`) that drops `verify`
  into CI with a real non-zero exit code on a broken chain.
- 8 progressive teaching chapters (`docs/`), 5 runnable per-topic examples
  (`examples/`), and a full API reference grounded in the actual `__all__`.

## Feature / API table

| feature | entry point | grounded in |
|---|---|---|
| open/create a journal | `SagJournal.open(path, schema)` | `sqlite3_sag/query.py` |
| append a chained entry | `j.remember(content, kind=..., tags=..., metadata=...)` | `sqlite3_sag/ingest.py` |
| write a durable (unchained) fact | `j.record_fact(claim, source_episode_id=...)` | `sqlite3_sag/ingest.py` |
| invalidate a fact | `j.invalidate_fact(fact_id)` | `sqlite3_sag/ingest.py` |
| verify the hash chain | `j.verify()` / `j.head_hash()` | `sqlite3_sag/chain.py` |
| search the journal | `j.recall(text, limit=10)` | `declared_core.hybrid_query` |
| list recent entries | `j.recent(limit=10, kind=None)` | `sqlite3_sag/query.py` |
| register-before-emit gate | `JournalSchema.validate_kind(kind)` | `sqlite3_sag/schema.py` |
| refuse-to-pretend gate | `check_payload(content, metadata)` | `sqlite3_sag/payload.py` |
| keyed (HMAC) chain mode | `JournalSchema(hash_alg="hmac-sha256")`, `hash_key=...` | `sqlite3_sag/chain.py` |
| conformance fixtures | `sqlite3_sag.conformance.check_fixture(fixture)` | `sqlite3_sag/conformance.py`, `fixtures/` |
| CLI | `sqlite3-sag append\|verify\|recent` | `sqlite3_sag/cli.py` |
| project_memory compat | `from project_memory import MemorySchema, ProjectMemory` | `project_memory/__init__.py` |

## Prerequisites

- **Python `>=3.10`** (declared in `pyproject.toml`; CI tests 3.10 and 3.12).
- **stdlib `sqlite3` built with FTS5** — required for recall (`declared_core`
  uses FTS5 virtual tables). Standard in CPython's official builds; this
  checkout was verified against `libsqlite3` `3.46.1` with `ENABLE_FTS5`
  present in `sqlite3.connect(":memory:").execute("PRAGMA compile_options")`.
- **Zero required third-party packages** — `pyproject.toml` declares
  `dependencies = []`.
- **Optional:** `numpy>=1.21` only if you use `declared_core`'s dense
  (semantic) recall directly — not required for anything `SagJournal`
  exposes today (see `docs/04-recall.md`).
- **Optional (dev):** `pytest>=7.0`, via the `[dev]` extra.

## Annotated repo layout

```
sqlite3-sag/
├── PROTOCOL.md            the versioned journal protocol (sag-journal/0.1-draft)
├── README.md               this file
├── HOW-TO-USE.md            task-oriented "I want to do X" companion to docs/
├── CLAUDE.md                 agent guide: invariants, architecture, what NOT to do
├── CONTRIBUTING.md            the change loop, fixture/vendoring/dependency rules
├── CHANGELOG.md                 keepachangelog-format history
├── RELEASE-NOTES.md              per-release narrative
├── ROADMAP.md                     dense booster (v1.x), C extension (v2), X1 fixture freeze
├── CODEBASE-REPORT.md              measured, command-grounded facts about this checkout
├── LICENSE / NOTICE                 Apache-2.0
│
├── sqlite3_sag/                     the primitive
│   ├── chain.py                       the hash chain: preimage, compute_hash, verify
│   ├── schema.py                       JournalSchema, DEFAULT_KINDS, register-before-emit
│   ├── payload.py                       refuse-to-pretend admissibility gate
│   ├── ingest.py                         remember() -- the one atomic append transaction
│   ├── query.py                           SagJournal -- append/recall/verify facade
│   ├── store.py                            connect() + DDL + old-DB migration
│   ├── conformance.py                       run_fixture / check_fixture
│   └── cli.py                                append/verify/recent subcommands
│
├── declared_core/                    vendored retrieval engine (see VENDORED.json)
├── project_memory/                    compat shim (re-exports sqlite3_sag under old names)
├── fixtures/                           conformance fixtures (generated, not hand-written)
├── tests/                               25 tests across 2 files
├── tools/                                gen_fixtures.py, revendor.py, verify_standalone.sh
├── docs/                                  8 numbered progressive chapters
└── examples/                               5 runnable, per-topic scripts
```

## Design choices — why it's built this way

- **Facts are never hash-chained.** A fact can be superseded or invalidated;
  a mutable row cannot honestly sit inside an append-only chain. Only
  `episodes` — the append-only entry log — is chained. See PROTOCOL.md §2.
- **The physical table name is never hashed.** `GENESIS` is a flat
  all-zero constant, not derived from a table name — so an `episodes` table
  and an `events` table hash identically for identical logical inputs.
  Cross-stream splice-protection is opt-in via the schema's `ns` field, not
  an accident of naming. See `docs/02-the-hash-chain.md`.
- **Unkeyed SHA-256 is the default, HMAC is opt-in.** An unkeyed chain
  proves internal self-consistency and needs no shared secret — the right
  default for a single-writer, non-adversarial journal. `hmac-sha256` closes
  the "attacker with write access recomputes everything" gap for the
  settings that need it, at the cost of key management.
- **No backfill by default.** A retroactive hash chain over pre-existing
  rows cannot prove those rows weren't altered before the backfill ran —
  only that they weren't altered *after*. Faking the stronger claim would be
  dishonest, so old rows stay `unchained` and `verify()` reports them as
  such (`unchained: N`), rather than silently misrepresenting their
  provenance. See PROTOCOL.md §11.
- **`declared_core` is vendored, not a PyPI dependency.** A byte-identical,
  drift-guarded in-repo copy (`VENDORED.json` + `tools/revendor.py`) means
  this package installs and runs standalone — no `PYTHONPATH` coupling to a
  sibling repo, no unpublished-package dependency to resolve.
- **Dense recall is deliberately not wired into `SagJournal.recall()`
  today.** `declared_core` supports it, but wiring it into the journal by
  default would pull `numpy` onto the default path — this release keeps
  BM25 + structural as the $0 floor and treats dense as a documented, opt-in
  future extension. See `ROADMAP.md`.
- **Both write-time gates fail loud, never silently.** An undeclared `kind`
  or an inadmissible payload raises immediately, before the row touches the
  chain. A journal is worth trusting only if what it refuses to record is as
  legible as what it does record.

## Back-compat

Code written against `project_memory`'s journal surface runs unchanged: `MemorySchema` and
`ProjectMemory` are aliases of `JournalSchema` / `SagJournal`, and the top-level
`project_memory` shim re-exports them. (Don't co-install the shim with the original
`project_memory` — it is the successor, and the name collides by design.)

## Not in this primitive

The natural-language *ask* surface, the synthesis-mud epistemic guard, dense embeddings,
and the portfolio brain stay in the fuller `project_memory` library. Dense recall is a
documented optional booster; a `sqlite-vec`-style **C loadable extension** form is planned
(v2) — this v1 is the pure-Python protocol + reference library.

## Recommended reading paths

**Novice — never used sqlite3-sag before:**
`docs/01-quickstart.md` → `docs/03-register-before-emit-and-refuse-to-pretend.md` →
`docs/04-recall.md` → `HOW-TO-USE.md`

**Expert — want the protocol internals and the interop story:**
`PROTOCOL.md` → `docs/02-the-hash-chain.md` →
`docs/05-conformance-and-provider-neutrality.md` → `docs/08-api-reference.md`

**Just want to verify a chain from a shell / CI job:**
`docs/07-cli.md` (`sqlite3-sag verify`, exit-code contract)

**Just migrating from `project_memory`:**
`docs/06-compat.md` + `examples/compat_shim_migration.py`

**Just want to implement this protocol in another language:**
`PROTOCOL.md` §5/§10/§12 → `docs/05-conformance-and-provider-neutrality.md` →
`examples/external_adapter_conformance.py` (a from-the-spec-alone reference walk)

**Agents/maintainers — before touching the code:**
`CLAUDE.md` (load-bearing invariants, architecture, what NOT to do)

## Contributing

See `CONTRIBUTING.md` — the local change loop mirrors CI exactly (tests,
compile-check, vendoring drift guard, fixture regeneration, the example
smoke test), plus the specific rules for touching the hash chain,
`declared_core/`, or adding a dependency.

## Acknowledgements

`sqlite3-sag` is extracted and generalized from `project_memory`'s journal
core — the append-only entries/facts model, the register-before-emit
discipline, and the BM25 + structural recall path all originate there. The
tamper-evident hash chain, the payload-admissibility gate, `PROTOCOL.md`,
and the conformance fixtures are original to this project. The retrieval
engine `declared_core` is a separate, vendored sibling package. `PROTOCOL.md`
is written to be jointly reconciled with the SAG Video side of the same
provider-neutral family (the X1-CLAUDE-002 delegation request) — see
`docs/05-conformance-and-provider-neutrality.md` and `ROADMAP.md`.

---

Authored by **Eyal Nof**. Apache-2.0. Provider-neutral by construction.

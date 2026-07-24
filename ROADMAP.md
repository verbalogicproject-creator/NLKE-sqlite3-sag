# Roadmap

This roadmap distinguishes what's shipped (`v0.1.0` — see `RELEASE-NOTES.md`)
from what's planned. Nothing below is implemented yet; each item states what
would need to be true for it to land, grounded in the current code.

## v1.x — a dense (semantic) recall booster, opt-in

**Where it stands today:** `declared_core` already has the pieces —
`declared_core.retrieval.dense.NumpyVectorIndex` (brute-force cosine over an
in-memory matrix, built once, queried via `.search(query, limit)`) and
`declared_core.hybrid_query(..., dense=your_index)` fuses it in as a fourth
signal alongside BM25/structural/rules. `declared_core`'s own CLI already
demonstrates it end-to-end (`declared_core/cli.py --dense`, with a toy
deterministic hash-embedder for zero-setup demos).

**What's missing:** `SagJournal.recall()` (`sqlite3_sag/query.py::_run`)
hardcodes `dense=None` — there is no parameter today to pass an embedder or
a pre-built `NumpyVectorIndex` into a journal's recall. Wiring it in needs:

- an opt-in constructor/recall parameter (so the $0, no-numpy floor for
  everyone who doesn't ask for it stays intact — see `CLAUDE.md`'s
  invariant on this),
- a documented way to (re)build the dense index as the journal grows (the
  current `NumpyVectorIndex.from_items` embeds a static snapshot; a live
  journal appends continuously),
- its own test coverage and a `docs/04-recall.md` update once it exists.

The `dense` extra already exists in `pyproject.toml`
(`[project.optional-dependencies] dense = ["numpy>=1.21"]`) — it's declared,
just not yet consumed by the journal itself.

## v2 — a `sqlite-vec`-style C loadable extension

**Where it stands today:** this repo is deliberately the pure-Python
protocol + reference library — the README and PROTOCOL.md both say so.
There is no C code, no compiled extension, and no build step anywhere in
this repository today; `sqlite3_sag/store.py::connect` uses only the stdlib
`sqlite3` module, with no `enable_load_extension`/`load_extension` call
anywhere in the codebase.

**What v2 would need:** a compiled SQLite loadable extension (in the shape
of `sqlite-vec`) that implements the hash-chain and/or the FTS-adjacent
retrieval math natively, for deployments that can afford a compiled
dependency and want the speed. This is explicitly a *later*, optional form
— the reference protocol and the pure-Python implementation remain the
portable baseline `dependencies = []` and Termux/Mac/Linux-anywhere claim
depend on. A v2 extension must not become a requirement for v1 users.

## The X1 joint fixture freeze with SAG Video

**Where it stands today:** `PROTOCOL.md` is explicitly `0.1-draft`, not
frozen. §13 lists four **open reconciliation items** that must be agreed
jointly with the SAG Video side of this cross-provider family before a
`0.1` freeze can happen:

1. Unicode normalization of `content` (SAG Video NFC-normalizes URI
   components; this reference does not normalize free-text `content` at
   all — one convention needs to be picked and pinned with a fixture).
2. The metadata number profile (this reference forbids floats outright;
   confirm floats-as-strings is the agreed convention on both sides).
3. Whether `ns` maps to SAG Video's `scope_uri` authority for cross-stream
   splice-protection.
4. Aligning receipt/observation `metadata` field names with SAG Video's
   `receipts`/`observations` columns so the same declared inputs round-trip
   through both producers.

**What "done" looks like:** each item resolved gets its own fixture added to
`fixtures/`, `tests/test_conformance.py` continues to pass against the
expanded fixture set, and `PROTOCOL.md`'s status line moves from
`0.1-draft` to `0.1`. Until then, an adapter built against today's
`PROTOCOL.md` should expect these four areas specifically to be the ones
most likely to shift.

## Explicitly not planned

- Multi-writer consensus, multi-region replication, or storage-backend
  equivalence claims — PROTOCOL.md §1 states these are out of scope by
  design, not a gap to be filled later. Conformance proves hash-chain
  parity; it does not and will not claim to prove crash/isolation
  equivalence across backends.
- A default (non-opt-in) chain backfill over pre-existing unchained rows —
  see `CLAUDE.md`'s invariant against this. If a backfill tool ever ships,
  it stays opt-in and honestly labeled as a notarization point, never a
  proof of the past.

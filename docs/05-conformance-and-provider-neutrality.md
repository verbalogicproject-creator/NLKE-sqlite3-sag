# 05 — Conformance and provider neutrality

`sqlite3-sag`'s Python package is the *reference implementation* of a
versioned, provider-neutral protocol — **PROTOCOL.md**
(`sag-journal/0.1-draft`). This chapter is about the contract, not the
library: what "conformant" means, how the shipped fixtures pin it, and how an
independent producer proves it without touching this codebase.

## The X1-CLAUDE-002 story

PROTOCOL.md opens with why this document exists: it is "the framework side's
answer to the cross-provider delegation request **X1-CLAUDE-002**" — a
request to define the `project_memory` → `sqlite3-sag` journal-protocol
boundary and fixtures for register-before-emit, idempotency, causal receipts,
claims, observations, trust degradation, and committed-vs-observed, with
telemetry explicitly kept outside the journal. The point: this journal's wire
format is meant to be implemented by producers that are not this Python
package, not even in Python — the SAG Video side of the same family is named
explicitly as the other conformance target. Nothing in PROTOCOL.md is
Claude-, OpenAI-, or model-specific.

## What "conformant" means

PROTOCOL.md §12:

> A producer is conformant when, for every fixture in `fixtures/`, its
> adapter reproduces — byte-for-byte — each chained row's
> `seq`/`prev_hash`/`row_hash` and the `verify()` outcome.

The four shipped fixtures (`fixtures/*.json`):

| fixture                 | proves                                                    |
|--------------------------|-----------------------------------------------------------|
| `basic_two_rows`         | the canonical row hashes for two clean chained rows        |
| `idempotent_reinsert`    | a duplicate `id` is a no-op — one row, chain unadvanced     |
| `tamper_content`         | a mutated row → `verify()` reports `row-hash-mismatch`      |
| `sequence_gap`           | a deleted row → `verify()` reports `sequence-gap`           |

Each fixture is plain JSON: `inputs` (pinned `id`/`created_at` so results are
deterministic), optional `tamper` / `delete_seq` operations, and an
`expected` block (`rows`, `verify`, `count`). Nothing about SQLite, Python,
or this repo's internal module layout leaks into the fixture format — it's a
description any adapter, in any language, can read and reproduce.

## The reference writer: sqlite3_sag.conformance

`sqlite3_sag/conformance.py` is this repo's own conformance harness:

```python
from sqlite3_sag.conformance import run_fixture, check_fixture
import json

fixture = json.loads(open("fixtures/basic_two_rows.json").read())
errors = check_fixture(fixture)   # [] means it passed
```

`run_fixture` replays a fixture's `inputs` through `SagJournal` (an in-memory
database, side-effect free) and returns `{"rows": [...], "verify": {...},
"count": N}`. `check_fixture` compares that against the fixture's `expected`
block and returns a list of human-readable mismatches. This is exactly what
`tests/test_conformance.py::test_fixture_reproduces` runs, parametrized over
every file in `fixtures/`.

`tools/gen_fixtures.py` is the inverse direction: it runs the reference
writer forward and **writes** `fixtures/*.json` from a hardcoded skeleton of
inputs. CI runs it and asserts a clean `git diff` — if regenerating the
fixtures from the reference implementation produces any change at all, the
canonical serialization or hash-chain algorithm drifted, and CI fails
(`.github/workflows/ci.yml`, step "Conformance fixtures regenerate no-op").

## Writing an external adapter — without importing this package at all

The strongest proof that PROTOCOL.md is a real, implementable contract (not
prose that only makes sense next to this Python source) is to follow it with
zero help from `sqlite3_sag.chain`. `examples/external_adapter_conformance.py`
does exactly that: it re-derives the canonical preimage and SHA-256 row hash
directly from PROTOCOL.md §5.1's field list and separator rules, using
nothing but `hashlib` and `json`, then checks the result against the
committed fixtures byte-for-byte:

```python
GENESIS = "0" * 64

def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")

def row_hash(*, ns, seq, prev, id, kind, content, session_id, batch,
             tags, metadata, method, schema_version, created_at):
    preimage = {"v": 1, "ns": ns or "", "seq": seq, "prev": prev, "id": id,
                "kind": kind, "content": content, "session_id": session_id,
                "batch": batch, "tags": tags, "metadata": metadata,
                "method": method, "schema_version": schema_version,
                "created_at": created_at}
    return hashlib.sha256(canonical_bytes(preimage)).hexdigest()
```

The one gotcha this example surfaced while it was being written (see chapter
02): a missing `metadata` on the wire must default to `{}` in the preimage,
not `None`/`null` — that's how the reference producer (`ingest.remember`)
stores it. An adapter that gets this default wrong will produce hashes that
look plausible but don't match the fixtures.

A real external adapter (a different language, a different store) would
follow the same shape: implement a `writer(fixture) -> {"rows", "verify",
"count"}`-compatible callable and assert equality against the fixture's
`expected` block — matching `check_fixture`'s comparison contract without
needing to import it.

## Honest limits (PROTOCOL.md §1, §13)

- **Out of scope:** bounded runtime *telemetry*. The journal is for the
  durable causal record — receipts, observations, claims, decisions — never
  for a UI-refresh event or a transient progress ping.
- **Not claimed:** multi-writer consensus, multi-region replication, or
  storage equivalence across backends. Passing conformance proves hash-chain
  parity; it does not prove crash-safety or isolation guarantees for a
  different backend — those must be tested per-backend.
- **Open reconciliation items** (§13 of PROTOCOL.md) are listed explicitly as
  *not yet frozen*: Unicode normalization of `content`, the metadata number
  profile, `ns` ↔ scope mapping, and receipt/observation field-name
  alignment with the SAG Video side. `0.1-draft` status means these are
  fixture-tested today but not yet jointly agreed.

## Verify your build

```bash
pytest -q tests/test_conformance.py          # 9 passed (8 fixtures + 1 existence check)
python tools/gen_fixtures.py                 # regenerate; should be a no-op on a clean tree
python examples/external_adapter_conformance.py
# Verify your build: ok (2 fixtures reproduced from the spec, no sqlite3_sag import)
```

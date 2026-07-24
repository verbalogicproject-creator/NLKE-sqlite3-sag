# Codebase report

A factual snapshot of this repository — every number below was measured
against this checkout (commands shown), not estimated.

## Size

```
$ find . -name '*.py' -not -path './.git/*' | wc -l
36
```

36 Python files, 4,103 total lines (`find . -name '*.py' -not -path './.git/*' | xargs cat | wc -l`),
split:

| package | LOC | files | role |
|---|---|---|---|
| `sqlite3_sag/` | 1,304 | 10 | the primitive: chain, gates, journal object, CLI, conformance harness |
| `declared_core/` | 1,788 | 15 | vendored retrieval engine (BM25 + structural + RRF + dimensions) |
| `project_memory/` | 58 | 1 | compat shim (re-exports only) |
| `tests/` | 255 | 2 | 21 tests across 2 files |
| `tools/` | 287 | 2 | fixture generator, vendoring drift guard |
| `examples/` | 403 | 5 | runnable, per-topic demonstrations |
| `conftest.py` | 8 | 1 | pytest sys.path setup (no-install test running) |

## Tests

```
$ pytest -q --collect-only | grep -c '::'
21
```

- `tests/test_sqlite3_sag.py` — 16 tests: extraction parity (2), chain
  monotonicity (1), tamper detection across all three break classes (3),
  idempotency (2), chain-disabled + recall + payload-gate degradation (4),
  `hmac-sha256` mode (2), old-database migration (1), plus the register-
  before-emit gate (1).
- `tests/test_conformance.py` — 5 tests: one per fixture file
  (`basic_two_rows`, `idempotent_reinsert`, `tamper_content`,
  `sequence_gap`), parametrized, plus a fixture-directory-not-empty guard.

All 21 pass on Python 3.14 in this environment; CI (`.github/workflows/ci.yml`)
runs the same suite on 3.10 and 3.12.

## Public API surface

```
$ python -c "import sqlite3_sag; print(len(sqlite3_sag.__all__))"
26
```

26 names in `sqlite3_sag.__all__` — see `docs/08-api-reference.md` for the
full, grounded per-symbol table. One main object (`SagJournal`, aliased as
`ProjectMemory`), one schema class (`JournalSchema`, aliased as
`MemorySchema`), the tamper-evidence layer (`verify`, `head_hash`,
`compute_hash`, `preimage`, `canonical_bytes`, `genesis`, `GENESIS`,
`CHAIN_VERSION`), the payload gate (`check_payload`,
`InadmissiblePayload`), the functional write API (`remember`, `record_fact`,
`invalidate_fact`), and store helpers (`connect`, `new_id`, `now_iso`).

## Runtime dependencies

```
$ grep -A2 '^dependencies' pyproject.toml
dependencies = []
```

Zero required runtime dependencies. Every top-level import across
`sqlite3_sag/*.py` is either stdlib (`hashlib`, `hmac`, `json`, `sqlite3`,
`uuid`, `datetime`, `argparse`, `re`, `typing`) or an in-repo module
(`declared_core`, vendored — see below). One optional extra:
`dense = ["numpy>=1.21"]`, imported lazily inside function bodies in
`declared_core/retrieval/dense.py`, never at module load time.

## Vendoring

```
$ cat VENDORED.json
{
  "vendored": [
    {"name": "declared_core", "source_version": "0.1.0",
     "tree_sha": "blake2b:28f5a6fe4434a1b27123cea8b01dec4605e4fd2b286e6ec7e6ecb804746b3a19", ...}
  ]
}
$ python tools/revendor.py check
✓ declared_core: in sync
```

`declared_core` (1,788 LOC, the BM25 + structural + RRF + dimensions
retrieval engine) is a byte-identical, drift-guarded in-repo copy of a
sibling package — not a PyPI dependency, not a `PYTHONPATH` coupling.
`tools/verify_standalone.sh` proves the whole package installs and passes
its test suite in a fresh venv with no sibling package separately
installed, and with numpy absent.

## Protocol and conformance surface

- `PROTOCOL.md` — `sag-journal/0.1-draft`, 263 lines, 13 numbered sections.
- `fixtures/` — 4 JSON fixture files, each pinning exact chained-row hashes
  and `verify()` outcomes.
- `sqlite3_sag/conformance.py` — 127 lines: `run_fixture` (the reference
  writer) and `check_fixture` (the comparator any external adapter's own
  writer can be checked against).

## What lives where (module map)

```
sqlite3_sag/
├── __init__.py       public API surface (__all__, PROTOCOL_VERSION)
├── chain.py           the hash chain: preimage, compute_hash, verify
├── schema.py           JournalSchema, DEFAULT_KINDS, register-before-emit gate
├── payload.py           refuse-to-pretend admissibility gate
├── ingest.py             remember() -- the one atomic append transaction
├── query.py               SagJournal -- append/recall/verify facade
├── store.py                connect() + DDL + old-DB migration
├── conformance.py           the fixture runner (run_fixture/check_fixture)
├── cli.py                    append/verify/recent subcommands
└── __main__.py                 python -m sqlite3_sag entry point

declared_core/          vendored retrieval engine (see VENDORED.json)
project_memory/          compat shim (re-exports sqlite3_sag under old names)
fixtures/                  conformance fixtures (generated, not hand-written)
tests/                       21 tests across 2 files
tools/                         gen_fixtures.py, revendor.py, verify_standalone.sh
docs/                           8 numbered progressive chapters
examples/                        5 runnable, per-topic scripts
```

## How this report was produced

Every number above came from running a command against this exact checkout
(shown inline) — `find`, `wc`, `pytest --collect-only`, `python -c` against
the live `sqlite3_sag.__all__`, `grep` against `pyproject.toml`, and
`python tools/revendor.py check`. If a future change makes any of these
numbers stale, regenerate them with the same commands rather than
hand-editing this file's numbers.

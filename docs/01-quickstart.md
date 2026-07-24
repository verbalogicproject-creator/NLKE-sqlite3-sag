# 01 — Quickstart: install, first append, first verify

This chapter gets you from zero to a verified, tamper-evident journal in one
sitting. Every snippet below is real — copy-paste it, or run
`examples/append_and_verify.py`, which is this same walkthrough as a script.

## Install

From a checkout:

```bash
pip install -e ".[dev]"     # runtime deps are zero; [dev] adds pytest
```

`pyproject.toml` declares `dependencies = []` — the runtime install pulls in
nothing beyond the Python standard library. `sqlite3-sag` requires Python
`>=3.10` (also declared in `pyproject.toml`; this repo's CI matrix tests 3.10
and 3.12).

## Open a journal, declare your kinds

Every entry has a `kind`, and every `kind` must be declared **before** you can
append it — this is *register-before-emit*, the journal's signature
discipline (chapter 03 goes deep on it). `DEFAULT_KINDS` gives you seven
generic ones; add your own domain kinds alongside them:

```python
from sqlite3_sag import SagJournal, JournalSchema, DEFAULT_KINDS

schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"))
j = SagJournal.open("journal.db", schema)     # or ":memory:" for ephemeral
```

`DEFAULT_KINDS` is `("decision", "gotcha", "insight", "invariant", "task",
"milestone", "general")` — see `sqlite3_sag/schema.py`.

## Append

```python
j.remember("retrieval 'auth flow' -> src/login.py [bm25] score=0.031",
           kind="sag.retrieval", tags=["declared-grep", "bm25"])
j.remember("retrieval 'signup' -> src/signup.py [bm25] score=0.028",
           kind="sag.retrieval", tags=["declared-grep", "bm25"])
```

Each `remember()` call is one atomic SQLite transaction: it takes the write
lock, reads the current chain head, computes this row's `seq` / `prev_hash` /
`row_hash`, and does exactly one `INSERT`. See `sqlite3_sag/ingest.py`.

## Verify

```python
>>> j.verify()
{'ok': True, 'break': None, 'at_seq': None, 'at_id': None, 'expected': None,
 'found': None, 'checked': 2, 'unchained': 0,
 'head_hash': '<64-hex-chars>', 'alg': 'sha256'}
```

`checked` is how many rows verified good; `head_hash` is the current chain
tip — checkpoint it somewhere out-of-band (a config file, another system) if
you want tamper-evidence against an attacker with write access to *this*
database too (chapter 02 explains why that matters).

## Tamper detection, live

```python
>>> j.conn.execute("UPDATE episodes SET content='forged' WHERE seq=1")
>>> j.verify()["break"]
'row-hash-mismatch'
```

Nothing special happened here — `episodes` is a plain SQLite table, and this
`UPDATE` is a plain SQL statement. `verify()` doesn't watch for writes; it
recomputes the hash chain from genesis on every call and reports the first
place the stored `row_hash` no longer matches what the row's *current*
content re-derives to.

## Recall over your own journal

```python
>>> j.recall("auth")
[{'table': 'episodes', 'id': '...', 'content': "retrieval 'auth flow' -> ...",
  'kind': 'sag.retrieval', 'rrf_score': 0.0269, 'rrf_sources': ['bm25', ...],
  ...}]
```

`recall()` is BM25 + structural expansion over the journal itself — chapter
04 covers it. No embeddings, no network, no API key.

## The CLI

The same operations from a shell, once installed:

```bash
sqlite3-sag append journal.db "a decision" --kind decision
sqlite3-sag verify journal.db        # exits non-zero if the chain is broken
sqlite3-sag recent journal.db
```

Chapter 07 covers the CLI in full, including what a broken chain looks like
from a shell / CI job.

## Verify your build

```bash
pytest -q                              # 25 passed
python examples/append_and_verify.py   # prints "Verify your build: ok"
```

Both commands are real — run them from the repo root now. If either fails,
something in your checkout differs from what these docs describe; the repo's
own test suite is the ground truth, not this prose.

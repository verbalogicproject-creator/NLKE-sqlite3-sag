# How to use sqlite3-sag

A task-oriented companion to `docs/` — "I want to do X" rather than "here is
chapter N". Every snippet below is real; if you want the why behind any of
it, the linked chapter has the full grounding.

## I want to journal decisions/gotchas for my own project

```python
from sqlite3_sag import SagJournal, JournalSchema, DEFAULT_KINDS

schema = JournalSchema(kinds=DEFAULT_KINDS)   # decision, gotcha, insight, invariant, task, milestone, general
j = SagJournal.open("my-project.db", schema)

j.remember("chose SQLite over Postgres for the journal store", kind="decision")
j.remember("the FTS5 trigger fires once per insert, not once per row change", kind="gotcha")
```

→ `docs/01-quickstart.md`

## I want to add my own entry kinds

Declare them up front — an undeclared kind raises rather than being
silently recorded:

```python
schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval", "sag.context_load"))
```

Namespace domain kinds (`sag.*`, `video.*`, …) so two producers' vocabularies
don't collide — this is PROTOCOL.md's recommendation, not enforced by code.

→ `docs/03-register-before-emit-and-refuse-to-pretend.md`

## I want to prove my journal hasn't been tampered with

```python
result = j.verify()
if not result["ok"]:
    raise SystemExit(f"journal integrity broken: {result['break']} at seq {result['at_seq']}")
```

For an adversarial threat model (an attacker with write access to the
database), use keyed `hmac-sha256` mode and keep the key out-of-band:

```python
j = SagJournal.open("journal.db",
                     JournalSchema(hash_alg="hmac-sha256"),
                     hash_key=my_secret_key)   # never store this in the db
```

Checkpoint `j.head_hash()` somewhere the same attacker doesn't also
control (a separate system, a signed log) if you need tamper-evidence even
against an attacker who can rewrite the whole database file.

→ `docs/02-the-hash-chain.md`

## I want to search my own journal

```python
hits = j.recall("sqlite storage decision", limit=5)
for h in hits:
    print(h["table"], h["id"], h.get("rrf_score"), h["content"] if h["table"] == "episodes" else h["claim"])
```

No embeddings needed — BM25 + structural expansion (shared kind/tags, the
fact→episode link) covers a surprising amount of ground. Dense (embedding)
recall exists in the vendored engine but is not wired into
`SagJournal.recall()` in this release — see `ROADMAP.md` if you need it.

→ `docs/04-recall.md`

## I want to run this from a shell script / CI job

```bash
sqlite3-sag append journal.db "deployed v1.2.3" --kind milestone
sqlite3-sag verify journal.db || exit 1   # non-zero exit on a broken chain
sqlite3-sag recent journal.db --limit 5
```

→ `docs/07-cli.md`

## I have code written against project_memory's MemorySchema/ProjectMemory

Nothing to change:

```python
from project_memory import DEFAULT_KINDS, MemorySchema, ProjectMemory

mem = ProjectMemory.open("journal.db", MemorySchema(kinds=DEFAULT_KINDS))
mem.remember("...", kind="decision")
```

`MemorySchema` and `ProjectMemory` are the exact same classes as
`JournalSchema`/`SagJournal` — not reimplementations. Just don't co-install
this package's `project_memory` shim alongside the original `project_memory`
distribution (the name collides by design).

→ `docs/06-compat.md`

## I have a database from before the hash chain existed

Just open it — the chain columns are added in place, and old rows are left
honestly `unchained` (not backfilled, not faked):

```python
j = SagJournal.open("old-project.db", JournalSchema(kinds=DEFAULT_KINDS))
j.verify()   # {'ok': True, 'checked': 0, 'unchained': N, ...} for a fully-legacy db
```

Every append from here forward is chained from `GENESIS`.

→ `docs/06-compat.md`

## I want to write facts (durable, revisable claims), not just log entries

```python
j.remember("we chose SQLite over Postgres", kind="decision", id="d1")
j.record_fact("the journal store is SQLite", source_episode_id="d1")

# later, if the decision changes:
new_fact = j.record_fact("the journal store is SQLite + a WAL-mode replica",
                          source_episode_id="d1", supersedes="<old fact id>")
```

Facts are deliberately **not** hash-chained — they mutate (`supersede`,
`invalidate`), and a mutable row can't be part of an append-only chain
without lying about what "append-only" means. Only the entry log
(`episodes`) is chained.

→ `docs/02-the-hash-chain.md`, PROTOCOL.md §2

## I'm implementing this protocol in a different language / store

Read `PROTOCOL.md` (the frozen wire contract, especially §5.1's canonical
preimage) and reproduce the four fixtures in `fixtures/*.json` byte-for-byte.
`examples/external_adapter_conformance.py` is a from-the-spec-alone
reference walk you can compare your own implementation against without
importing anything from this package.

→ `docs/05-conformance-and-provider-neutrality.md`

## I want to confirm this repo actually works standalone, with no numpy

```bash
bash tools/verify_standalone.sh
```

Installs into a fresh venv, confirms the wheel (not some sibling checkout)
is what actually imports, uninstalls numpy if present and re-runs
append/verify/recall to prove the $0 floor, then runs the full test suite.

→ `CLAUDE.md`

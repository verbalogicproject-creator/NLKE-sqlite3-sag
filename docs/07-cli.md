# 07 — The CLI

`sqlite3-sag` ships a small command-line front door
(`sqlite3_sag/cli.py`) — deliberately minimal, since the primitive is a
library first. Three subcommands, each opening the target database with
`DEFAULT_KINDS` plus (for `append`) whatever `--kind` you pass:

```python
def _journal(path, extra_kinds=()):
    kinds = (*DEFAULT_KINDS, *[k for k in extra_kinds if k not in DEFAULT_KINDS])
    return SagJournal.open(path, JournalSchema(kinds=kinds))
```

That means `append --kind anything` always works from the CLI — the CLI
declares your kind for you at open time, so the register-before-emit gate
(chapter 03) never trips on the command line. If you need a fixed, closed
kind vocabulary enforced across every writer, do that from your own script
against a `JournalSchema` you control — the CLI's per-call schema is
convenience, not policy.

Available both as `sqlite3-sag` (the installed console script,
`pyproject.toml`'s `[project.scripts]`) and `python -m sqlite3_sag`
(`sqlite3_sag/__main__.py`) — identical behavior either way.

## `append`

```bash
$ sqlite3-sag append journal.db "a decision" --kind decision
{"id": "d9149e37b7b246619751bb063ee76347", "kind": "decision", "fact_id": null,
 "seq": 1, "row_hash": "0c2ae25202451b0244bba2222922018a7419e8308bb6a1734605082b6e9204dc"}
```

`--tag` may be repeated (`--tag foo --tag bar`); output is the same dict
`SagJournal.remember()` returns, JSON-encoded.

## `verify`

```bash
$ sqlite3-sag verify journal.db
{
  "ok": true,
  "break": null,
  "at_seq": null,
  "at_id": null,
  "expected": null,
  "found": null,
  "checked": 1,
  "unchained": 0,
  "head_hash": "0c2ae25202451b0244bba2222922018a7419e8308bb6a1734605082b6e9204dc",
  "alg": "sha256"
}
```

**Exit code matters here:** `verify` exits `0` when `ok: true`, and **`1`**
when the chain is broken (`cli.py`: `return 0 if result["ok"] else 1`) — so
it drops into CI or a pre-commit check with no extra scripting:

```bash
$ sqlite3-sag verify journal.db && echo "chain intact" || echo "CHAIN BROKEN"
```

Confirmed against a deliberately tampered database:

```bash
$ sqlite3-sag verify /tmp/broken.db
{
  "ok": false,
  "break": "row-hash-mismatch",
  "at_seq": 1,
  ...
}
$ echo $?
1
```

## `recent`

```bash
$ sqlite3-sag recent journal.db
{"id": "d9149e37b7b246619751bb063ee76347", "content": "a decision", "kind": "decision",
 "batch": null, "tags": [], "created_at": "2026-...+00:00", "seq": 1}
```

One JSON object per line, newest first (`ORDER BY created_at DESC`),
optionally capped with `--limit N` (default 10). This calls
`SagJournal.recent()` directly — it is a plain `SELECT`, not a `recall()`
query, so it never touches BM25/structural/intent (chapter 04). Use `recent`
when you want "what was written lately"; use the library's `recall()` when
you want "what's relevant to this question".

## What the CLI deliberately does not do

There is no `sqlite3-sag recall` subcommand — recall requires a query
string plus (usually) programmatic handling of ranked hit dicts, which fits
a library call better than a CLI print. There is no subcommand for facts
(`record_fact` / `invalidate_fact`) or for `hmac-sha256` keyed mode (the CLI
always opens with the default `sha256` schema) — those are library-only
today. Reach for the Python API (chapters 01–04) for anything beyond
append/verify/recent.

## Verify your build

```bash
sqlite3-sag append /tmp/ci-journal.db "ci smoke entry" --kind decision
sqlite3-sag verify /tmp/ci-journal.db      # exits 0
```

This is the literal CI smoke test — see `.github/workflows/ci.yml`, step
"Smoke test — CLI (fresh journal, append + verify)".

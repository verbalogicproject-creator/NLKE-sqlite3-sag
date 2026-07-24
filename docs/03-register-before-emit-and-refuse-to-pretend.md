# 03 — Register-before-emit and refuse-to-pretend: the two write-time gates

Every `remember()` call runs through two independent gates before a row is
chained (`sqlite3_sag/ingest.py::remember`, in this order):

```python
schema.validate_kind(kind)      # 1. register-before-emit
check_payload(content, metadata, max_bytes=..., refuse_secrets=...)  # 2. refuse-to-pretend
```

Both **raise**, never silently misrecord. This chapter walks both gates
against `examples/register_before_emit.py` — run it alongside reading this.

## Gate 1 — register-before-emit

A `JournalSchema` declares a closed set of `kind`s up front
(`sqlite3_sag/schema.py`):

```python
schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"), max_content_bytes=64)
j = SagJournal.open(":memory:", schema)

j.remember("chose sqlite for the journal store", kind="decision")   # ok — declared
j.remember("this should never land", kind="video.render")           # raises ValueError
```

`validate_kind` (`JournalSchema.validate_kind`) is direct:

```python
def validate_kind(self, kind: str) -> None:
    if kind not in self.kinds:
        raise ValueError(f"unknown entry kind {kind!r}; declared kinds are {sorted(self.kinds)}. "
                          "Add it to JournalSchema(kinds=...).")
```

There is no "auto-add" path, no fallback kind, no silent coercion to
`"general"`. An undeclared kind is a bug in the caller, and the gate treats
it as one. This mirrors PROTOCOL.md §3: *"Appending an undeclared kind MUST
fail loudly (raise / reject), never be silently recorded."*

Why this matters in practice: `DEFAULT_KINDS` is a generic seven-kind
taxonomy (`decision, gotcha, insight, invariant, task, milestone, general`).
Any domain-specific kind — `sag.retrieval`, `sag.context_load`,
`video.render` — must be declared explicitly when you open the schema. This
is the same discipline PROTOCOL.md recommends namespacing domain kinds under
(`sag.*`, `video.*`, …) so two producers' vocabularies don't collide.

## Gate 2 — refuse-to-pretend (payload admissibility)

`check_payload` (`sqlite3_sag/payload.py`) runs three independent checks
before content is chained. All are deliberately conservative — the shipped
consumers pass short human-readable strings, and none of these checks trip
on ordinary journal prose:

**a. Size cap.** Content over `max_content_bytes` (schema default 64 KiB) is
refused — the journal is a semantic log, not a blob store:

```python
schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"), max_content_bytes=64)
j.remember("x" * 200, kind="decision")
# InadmissiblePayload: content is 200 bytes, over the 64-byte cap
# (the journal stores bounded semantic records, not blobs)
```

**b. Secret markers.** A small, deliberately *unambiguous* set of credential
shapes — PEM private-key headers, AWS access-key ids
(`_SECRET_MARKERS` in `payload.py`) — are refused outright:

```python
j.remember("leaked key: AKIAIOSFODNN7EXAMPLE", kind="decision")
# InadmissiblePayload: content matches a aws-access-key-id marker;
# credentials must not enter the journal
```

Toggle with `JournalSchema(refuse_secrets=False)` if your domain legitimately
needs to journal text that happens to match one of these patterns (rare, and
not the default).

**c. Metadata number/type profile.** `metadata` must be JSON built only from
`str` / `int` / `bool` / `null` (plus nested dict/list) — **floats and raw
bytes are refused**:

```python
j.remember("ok content", kind="decision", metadata={"confidence": 0.87})
# InadmissiblePayload: metadata.confidence: float values are not permitted
# (cross-language formatting is not byte-identical; use a string)

j.remember("ok content", kind="decision", metadata={"confidence": "0.87"})  # fine — it's a string
```

Why floats specifically: cross-language float formatting (`repr()` in
Python, `%g` in C, `Number.toString()` in JS) is not byte-identical, and the
canonical preimage (chapter 02) would stop hashing identically across
producers if a float ever entered it. The gate objects to the **type**, not
the value — represent fractional data as a string and it passes.

## Why the two gates are separate function calls

`validate_kind` and `check_payload` are independent, composable checks — a
caller integrating only the kinds discipline (say, a producer that already
trusts its own payload shapes) could call `validate_kind` without the
payload gate. In `remember()`, both always run, in that order, before the
chain-head read even happens — a rejected kind or payload never touches the
write lock.

## Verify your build

```bash
python examples/register_before_emit.py
# ok: appended kind=decision id=...
# refused (undeclared kind): unknown entry kind 'video.render'; ...
# refused (oversize content): content is 200 bytes, over the 64-byte cap ...
# refused (credential marker): content matches a aws-access-key-id marker; ...
# refused (float in metadata): metadata.confidence: float values are not permitted ...
# ok: the same value as a string metadata field is admissible
# Verify your build: ok

pytest -q -k "kind or payload"   # the gate-specific tests
```

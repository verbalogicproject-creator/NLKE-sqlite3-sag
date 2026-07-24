# 02 — The hash chain: seq, prev_hash, row_hash, and what verify() catches

This is the one thing `sqlite3-sag` adds that its source (`project_memory`)
never had: a way to *prove* the journal was not silently altered, reordered,
or dropped. The full wire contract lives in **PROTOCOL.md §5 and §10** — this
chapter walks the same ground grounded in the actual code
(`sqlite3_sag/chain.py`), building on the journal from chapter 01.

## The four columns

Every chained row in the `episodes` table carries (`sqlite3_sag/store.py`):

| column      | type    | meaning                                                          |
|-------------|---------|-------------------------------------------------------------------|
| `seq`       | INTEGER | 1-based, monotonic, assigned under a write lock                  |
| `prev_hash` | TEXT    | the predecessor row's `row_hash` (`GENESIS` for `seq == 1`)       |
| `row_hash`  | TEXT    | `H(canonical_preimage(row))` — binds this row into the chain      |
| `hash_alg`  | TEXT    | `sha256` (default) or `hmac-sha256`                               |

`GENESIS = "0" * 64` (`sqlite3_sag/chain.py`) — a flat, all-zero 64-hex-char
predecessor for the very first row. It's flat (not derived from the table
name) so that identical logical inputs hash identically whether they land in
a table called `episodes` or `events` — cross-stream splice-protection is
opt-in via the schema's `ns` field, not by leaking a physical table name into
the hash (PROTOCOL.md §5, "GENESIS").

## The canonical preimage — the interop contract

`row_hash = SHA256(canonical_bytes(preimage_object))`, where `preimage_object`
is built by `chain.preimage()` over exactly these semantic fields (the *set*
is the contract — see `PREIMAGE_FIELDS` in `chain.py`):

```
v, ns, seq, prev, id, kind, content, session_id, batch, tags, metadata,
method, schema_version, created_at
```

`canonical_bytes()` is `json.dumps(obj, sort_keys=True,
separators=(",", ":"), ensure_ascii=False).encode("utf-8")` — sorted keys,
compact separators, UTF-8, no ASCII-escaping. `tags` and `metadata` are
**parsed from their stored JSON text and re-canonicalized** before hashing
(`chain._as_json`), so a producer's incidental JSON-formatting (spacing, key
order) never enters the hash. One consequence worth knowing: **a
whitespace-only edit to the stored JSON text does not trip the chain** — the
hash protects semantic content, not the byte-exact stored representation.
That's the intentional trade for cross-language interop (PROTOCOL.md §5.1).

A gotcha worth stating explicitly (found while writing
`examples/external_adapter_conformance.py`): a `metadata` field you never
passed to `remember()` is **not** `null` in the preimage. `ingest.remember`
stores it as `json.dumps(metadata or {})`, so the preimage binds `{}`, not
`None`. An adapter that defaults a missing `metadata` to JSON `null` instead
of `{}` will NOT reproduce the fixture hashes.

`created_at` **is bound** into the hash. This does not make the timestamp
trustworthy (it's caller-supplied), but it does make the *recorded* value
tamper-evident, and it blocks reorder-by-rewriting-timestamps.

## verify() — walking the chain

```python
from sqlite3_sag import SagJournal, JournalSchema, DEFAULT_KINDS

j = SagJournal.open(":memory:", JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))
for i in range(3):
    j.remember(f"entry {i}", kind="sag.retrieval",
               id=f"{i:032d}", created_at=f"2026-01-01T00:00:0{i}+00:00")

j.verify()
# {'ok': True, 'break': None, ..., 'checked': 3, 'unchained': 0, 'head_hash': '...', 'alg': 'sha256'}
```

`verify()` walks chained rows **in `seq` order — never `created_at`**,
recomputes `row_hash` from `GENESIS` forward, and returns the **first** break
it finds, classified. `unchained` counts rows with `seq IS NULL` (legacy rows
from before a chain existed, or rows appended with `hash_chain=False`) —
they're excluded from the walk, not treated as breaks.

## The three break classes

Each is a distinct, deliberate mutation and a distinct classification
(`sqlite3_sag/chain.py::verify`; mirrored by
`tests/test_sqlite3_sag.py::test_tamper_*` / `test_delete_row_sequence_gap`):

**1. `row-hash-mismatch`** — a row's content changed but its `row_hash`
didn't (because nobody who can pass verification could recompute a valid
hash without knowing the change was coming):

```python
j.conn.execute("UPDATE episodes SET content='forged' WHERE seq=2")
j.verify()  # -> {'ok': False, 'break': 'row-hash-mismatch', 'at_seq': 2, 'checked': 1, ...}
```

**2. `predecessor-mismatch`** — a row's `prev_hash` no longer points at the
actual predecessor's `row_hash` (someone rewired the chain's pointers):

```python
j.conn.execute("UPDATE episodes SET prev_hash=? WHERE seq=2", ("de" * 32,))
j.verify()  # -> {'ok': False, 'break': 'predecessor-mismatch', 'at_seq': 2, ...}
```

**3. `sequence-gap`** — a row is missing entirely (deleted), so the expected
`seq` never appears:

```python
j.conn.execute("DELETE FROM episodes WHERE seq=2")
j.verify()  # -> {'ok': False, 'break': 'sequence-gap', 'at_seq': 2, 'expected': 2, 'found': 3, ...}
```

In every case, `checked` tells you how many rows verified clean *before* the
break — that's how many entries you can still trust.

## The honest security envelope

An **unkeyed** `sha256` chain proves internal self-consistency — it detects
*accidental* corruption and naive tampering perfectly. But an attacker with
write access to the database can rewrite a row *and* recompute every
downstream hash into a new, internally-consistent forgery. The chain alone
cannot catch that. It is tamper-**evident** only against an out-of-band
trusted `head_hash`: store the head somewhere the attacker doesn't also
control, and compare.

`hash_alg="hmac-sha256"` closes that gap for a keyed setting — without the
key, downstream hashes can't be recomputed into a valid forgery:

```python
j = SagJournal.open(":memory:",
                     JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"),
                                   hash_alg="hmac-sha256"),
                     hash_key="s3cret")
j.remember("keyed entry", kind="sag.retrieval")
j.verify()                    # ok=True, uses the journal's own key
j.verify(key="wrong-key")     # -> break: 'row-hash-mismatch'
```

The key is supplied out-of-band (`hash_key=` at open time) and is **never
stored in the database**. Opening a `hmac-sha256`-schema journal and
appending without a key raises `ValueError`
(`tests/test_sqlite3_sag.py::test_hmac_without_key_raises`) — the gate fails
loud, it never silently falls back to unkeyed hashing.

## Chain-disabled mode

`JournalSchema(hash_chain=False)` still appends and still recalls — it just
never assigns `seq`/`prev_hash`/`row_hash`. Every row is `unchained`, and
`verify()` reports `ok=True, checked=0, unchained=N` (there's nothing to
break because nothing was ever chained). This is a legitimate, tested
degradation path (`test_chain_disabled_still_appends_and_verifies_trivially`)
— not every use of the journal needs tamper-evidence.

## Verify your build

```bash
python examples/append_and_verify.py
# ...
#   tamper detected: row-hash-mismatch at seq 2
# Verify your build: ok

pytest -q -k "tamper or chain or hmac or sequence_gap"   # the chain-specific tests
```

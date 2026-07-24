# The SAG Journal Protocol — `sag-journal/0.1-draft`

A **provider-neutral, versioned contract** for a durable, append-only, tamper-evident
causal journal. `sqlite3-sag`'s pure-Python package is the *reference implementation*;
this document is the contract an independent producer (any language, any store) can
implement and prove conformant against the shipped fixtures (`fixtures/`).

It is the framework side's answer to the cross-provider delegation request
**X1-CLAUDE-002** ("provide the `project_memory` → `sqlite3-sag` journal-protocol
boundary and fixtures for register-before-emit, revision/idempotency, causal receipts,
claims, observations, trust degradation, and committed-versus-observed; telemetry
remains outside the journal"). Nothing here is Claude-, OpenAI-, or model-specific.

> **Status.** `0.1-draft`. Frozen fields below are testable today via `fixtures/`. The four §13
> reconciliation items are **frozen** (jointly reconciled with SAG Video on 2026-07-24) and each is
> pinned by a fixture. The id advances to `0.1` only once both providers' adapters pass the full
> fixture set (§12) — SAG Video has independently reproduced the original four; the §13 fixtures are
> the next reproduction target.

---

## 1. Scope and non-goals

The journal records **declared, bounded, text/JSON semantic entries** in an append-only
log, and lets any holder **verify** the log was not silently altered, reordered, or
truncated.

- **In scope:** the durable causal side — entries (events), the receipts/observations/
  claims recorded *as* entries, register-before-emit, idempotency, the hash chain,
  committed-vs-observed.
- **Out of scope (a hard line):** bounded runtime **telemetry**. A runtime event may wake
  a UI or describe a transition; it must never become the durable journal. Producers keep
  telemetry in a separate, expiring store. (This mirrors the SAG Video side's 7-day /
  capped runtime cursor being distinct from its durable records.)
- **Not claimed:** multi-writer consensus, multi-region, or storage equivalence across
  backends. Passing conformance is necessary, not sufficient, to claim durability parity —
  crash/isolation/backup tests must be rerun per backend.

## 2. Core model

Two record classes; only the first is chained.

- **Entry** (an *event* / *episode*): one immutable row in the append-only log. Carries a
  stable `id`, a declared `kind`, a text `content`, optional `tags`/`metadata`, and — when
  chaining is on — `seq` / `prev_hash` / `row_hash` / `hash_alg`.
- **Fact** (optional, a *claim*): a durable, **mutable** assertion crystallized from an
  entry, with a supersede/invalidate lifecycle. Because facts mutate, they are **NOT**
  part of the hash chain. A conforming producer need not implement facts.

Receipts, observations, claims, and trust transitions are **not new tables** — they are
**entries with a declared `kind`** (§7). This keeps the contract small: one append-only,
chained log carries the whole causal record.

## 3. Register-before-emit (the signature discipline)

Every `kind` MUST be declared before an entry of that kind is appended. Appending an
undeclared kind MUST fail loudly (raise / reject), never be silently recorded.

```python
schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval", "sag.context_load"))
journal.remember("...", kind="sag.retrieval")   # ok
journal.remember("...", kind="undeclared")       # MUST raise
```

`DEFAULT_KINDS = (decision, gotcha, insight, invariant, task, milestone, general)`. A
producer MAY define any additional kinds; domain kinds SHOULD be namespaced
(`sag.retrieval`, `sag.context_load`, `video.render`, …).

## 4. The entry shape

| field            | type              | notes                                                            |
|------------------|-------------------|------------------------------------------------------------------|
| `id`             | string            | stable identity; the idempotency key (§6). Opaque.               |
| `kind`           | string            | declared (§3).                                                   |
| `content`        | string (UTF-8)    | bounded semantic text; not a blob, not secrets (§8).             |
| `session_id`     | string \| null    | optional grouping.                                               |
| `batch`          | string \| null    | optional grouping.                                               |
| `tags`           | JSON array        | strings.                                                         |
| `metadata`       | JSON object       | str/int/bool/null (+ nested); **no floats, no bytes** (§8).      |
| `method`         | string            | provenance stamp (how produced), e.g. `manual`.                  |
| `schema_version` | integer           | on-disk version stamp.                                           |
| `created_at`     | string (ISO-8601) | recorded timestamp; producer-supplied, tamper-bound (§5).        |
| `seq`            | integer \| null   | 1-based monotonic; `null` = unchained (§5, §9).                  |
| `prev_hash`      | hex \| null       | predecessor `row_hash`; genesis for `seq==1`.                    |
| `row_hash`       | hex \| null       | `H(canonical_preimage)` (§5).                                    |
| `hash_alg`       | string \| null    | `sha256` (default) or `hmac-sha256`.                             |

## 5. The hash chain (tamper-evidence)

Each chained entry binds itself to its predecessor:

```
seq       = predecessor.seq + 1           (1 for the first entry)
prev_hash = predecessor.row_hash          (GENESIS for seq == 1)
row_hash  = H( canonical_preimage )
GENESIS   = "0" * 64
H         = SHA-256            (hash_alg = "sha256", default)
          | HMAC-SHA256(key,·) (hash_alg = "hmac-sha256"; key supplied out-of-band)
```

### 5.1 Canonical preimage — the interop contract (FROZEN)

The preimage is **one canonical-JSON object** over the entry's *semantic* fields:

```
canonical_bytes(obj) = json(obj, sort_keys=true, separators=(",",":"),
                            ensure_ascii=false).encode("utf-8")

preimage_object = {
  "v":              1,                 # chain format version (domain separation)
  "ns":             <stream namespace> # "" by default; NOT the physical table name
  "seq":            <int>,
  "prev":           <hex prev_hash>,
  "id":             <string>,
  "kind":           <string>,
  "content":        <string>,
  "session_id":     <string|null>,
  "batch":          <string|null>,
  "tags":           <parsed JSON value>,     # re-canonicalized, not stored text
  "metadata":       <parsed JSON value>,     # re-canonicalized, not stored text
  "method":         <string>,
  "schema_version": <int>,
  "created_at":     <string>
}
```

Rules that make the hash **byte-identical across producers**:

- **Sorted keys, compact separators (`,`/`:`), UTF-8, no ASCII-escaping.** (Key *order* in
  the object literal is irrelevant — `sort_keys` canonicalizes it; the *set* of keys is
  the contract.)
- **`tags`/`metadata` are parsed and re-canonicalized**, so a producer's JSON-formatting
  quirk (spacing, key order) never enters the hash. Consequence (intentional): the hash
  protects *semantic* content, not byte-exact storage — a whitespace-only edit to stored
  JSON does not trip the chain.
- **Absent `tags`/`metadata` default to `[]` / `{}` respectively — never `null` and never
  omitted from the preimage.** The reference stores `json.dumps(tags or [])` /
  `json.dumps(metadata or {})`, so a produced row's preimage always carries an empty array /
  empty object there, not a null. An external adapter MUST apply the same defaulting before
  hashing (this exact point is what an independent reimplementation trips on first).
- **The physical table/stream name is NOT hashed.** So "episodes" and "events" produce
  identical hashes for identical logical inputs. Cross-stream splice-protection is opt-in
  via `ns` (e.g. set `ns = project_id`), not by leaking a table name.
- **`created_at` IS bound.** This does not make the timestamp *trustworthy* (it is
  producer-supplied); it makes the *recorded* value tamper-evident and blocks
  reorder-by-rewriting-timestamps.
- **Number/encoding profile:** `metadata` numbers are integers/booleans only. **Floats are
  forbidden** (cross-language float formatting is not byte-identical) — represent
  fractional values as strings. Raw bytes are forbidden. (§8 enforces this.)

### 5.2 Honest security envelope

- An **unkeyed** SHA-256 chain proves internal self-consistency. It is tamper-*evident*
  only against an **out-of-band trusted head**: compare a stored `head_hash` (the last
  entry's `row_hash`) to the value the journal now reports. An attacker with write access
  can otherwise rewrite a row and recompute every downstream hash into a consistent forgery.
- **`hmac-sha256`** closes that gap: without the key, downstream hashes cannot be
  recomputed. Recommended for adversarial/multi-writer settings. The key is supplied
  out-of-band and **never stored in the database**.

## 6. Idempotency and revision

- **Idempotency key = `id`.** Re-appending an existing `id` is a **no-op**: it MUST NOT
  advance the chain, consume a `seq`, or alter the existing row. (Reference: `INSERT OR
  IGNORE` + a `rowcount` check.) A producer with a `(scope, request_id)` idempotency key
  (e.g. SAG Video) maps it deterministically to `id` (e.g. a hash of the pair).
- **Revision (optional).** A monotonic per-scope integer MAY be carried in `metadata`
  (`{"revision": N, "parent_revision": N-1}`) for producers that version an aggregate.
  Revision integrity rides the same chain; the protocol does not mandate a separate column.

## 7. Receipts, observations, claims, trust — as declared kinds

The causal vocabulary is expressed as entries with declared kinds, not new tables:

- **Receipt** — a committed record that a command/action was performed. Suggested kind
  `sag.receipt`; `content` is human-readable; structured detail in `metadata`
  (`request_id`, `command`, `status`, `revision`).
- **Observation** — an **independent** evaluation of a receipt's result. Suggested kind
  `sag.observation`; `metadata` carries `receipt_id`, `observer`, `passed` (nullable),
  `inconclusive` (bool). **A missing/inconclusive observation MUST NOT resolve to
  success.**
- **Claim / lease** — a worker's atomic claim of work. Suggested kind `sag.claim`.
- **Trust transition** — a change in an actor's/result's trust state. Suggested kind
  `sag.trust`.

Producers MAY specialize these into their own tables internally; the **journal contract**
only requires that such records, when placed in the shared journal, are declared kinds and
obey §3–§6.

## 8. Refuse-to-pretend (payload admissibility)

Before an entry is chained, a conforming producer MUST refuse to journal what it cannot
faithfully canonicalize and chain:

- `content` over a size cap (reference default **64 KiB**) — the journal is a semantic log,
  not a blob store.
- `metadata` containing **floats** or **raw bytes**.
- **credentials** — unambiguous secret markers (PEM private-key headers, cloud access-key
  ids). (Toggleable; on by default.)

The principle: the journal will not *pretend* to have durably recorded a blob/secret it
cannot honestly represent.

## 9. Committed vs observed

- A recorded entry is **committed** — it asserts *"this was declared/done"*.
- **Observation is a separate, independently-authored entry** (§7). Committed ≠ observed.
- A result that cannot be independently observed MUST be reported as **pending /
  inconclusive / failed**, never as observed success — even when its producing code ran.

## 10. `verify()` — the checkable contract

Walk chained entries in `seq` order (never `created_at`), recompute from `GENESIS`, and
report the **first** break:

```
verify() -> {
  ok:        bool,
  break:     "sequence-gap" | "predecessor-mismatch" | "row-hash-mismatch" | null,
  at_seq:    int | null,     # the expected position where continuity broke
  at_id:     str | null,     # offending row id
  expected:  <int|hex> | null,
  found:     <int|hex> | null,
  checked:   int,            # rows verified good before the break
  unchained: int,            # rows with seq IS NULL (legacy / chain-disabled)
  head_hash: hex | null,     # last good row_hash — checkpoint this out-of-band
  alg:       str | null
}
```

Unchained rows (`seq IS NULL`) are excluded from the walk and reported via `unchained`.

## 11. Migration (old logs) — and an honest limit

Opening a pre-chain log: **add the chain columns in place** (`ALTER TABLE ADD COLUMN`,
default `NULL`); pre-existing rows stay **unchained** (`seq IS NULL`); only new appends are
chained; `verify()` reports the boundary via `unchained`.

Backfilling a chain over pre-existing rows is available but **must be labeled honestly**: a
retroactive chain **cannot prove the past** — it only establishes a *notarization point*
from backfill-time forward, and only if the resulting `head_hash` is checkpointed
out-of-band. The reference default does **not** backfill (it will not fake tamper-evidence).

## 12. Conformance

A producer is conformant when, for every fixture in `fixtures/`, its adapter reproduces —
byte-for-byte — each chained row's `seq`/`prev_hash`/`row_hash` and the `verify()` outcome.
The shipped fixtures: `basic_two_rows` (canonical hashes), `idempotent_reinsert` (dup id =
no-op), `tamper_content` (→ row-hash-mismatch), `sequence_gap` (→ sequence-gap). The
harness is `sqlite3_sag.conformance` (`run_fixture` / `check_fixture`); plug your writer in
and match the same `expected` blocks.

## 13. Reconciled joint decisions — FROZEN 2026-07-24

The four items below were reconciled jointly with the SAG Video side (OpenAI Codex) — Codex's
proposed answers (`sag-video-progress-x1-response-2026-07-24.ngf.md` §4) matched this reference's
defaults. They are now **frozen** and each is pinned by a conformance fixture. (The protocol id
stays `0.1-draft` until both providers' adapters pass the full fixture set — see §12; the *decisions*
here are frozen.)

1. **Free-text is NOT normalized — FROZEN.** `content` is preserved exactly after UTF-8 validation;
   NFC normalization applies to URI path components (SAG Video's `sag://` URIs), **never** to journal
   prose. An NFC-composed and an NFD-decomposed spelling of the same word are **distinct inputs with
   distinct hashes**. Pinned by `fixtures/unicode_distinct.json`.
2. **Number profile — FROZEN.** `metadata` carries no floats and no bytes. Adapters either refuse
   fractional values or encode them as schema-declared **decimal strings**; they never silently round.
   Pinned by `fixtures/refuse_float_metadata.json` (a nested float is refused).
3. **`ns` = the full canonical `scope_uri` — FROZEN.** In production, `ns` is the complete X1
   `scope_uri` (authority + scope-kind + scope-id), giving cross-stream splice-protection between
   providers with identical local ids. `ns=""` is reserved for explicitly-global conformance fixtures.
   `ns` binds into the hash: pinned by `fixtures/namespace_scoped.json` (same inputs, `scope_uri` ns →
   different hashes than the `ns=""` `basic_two_rows`).
4. **Receipt/observation metadata field names — FROZEN.** Pinned by
   `fixtures/receipt_observation_roundtrip.json`:
   - `sag.receipt` metadata: `receipt_id`, `request_id`, `command`, `status`, `actor`, `project_id`,
     `project_revision`; optional `trace_id`; and a bounded canonical `payload` or `payload_hash`
     (per the §13.2 number profile).
   - `sag.observation` metadata: `observation_id`, `receipt_id`, `observer`, `observer_mode`,
     `passed` (`bool|null`), `inconclusive`, optional `artifact_hash`, bounded `findings` or
     `findings_hash`, and `observed_at`.
   - **Recommended deterministic entry id** for these kinds:
     `sha256(scope_uri ‖ NUL ‖ kind ‖ NUL ‖ source_record_id_or_request_id)` — so a producer's
     `(scope, request_id)` idempotency maps to the journal `id` (§6). The observation entry must be
     **independently authored**; a receipt `status` alone never maps to observed success (§9).

---

*Reference implementation: `sqlite3-sag` (package `sqlite3_sag`), Apache-2.0, by Eyal Nof.
Provider-neutral by construction: the same declared inputs hash identically regardless of
producer or store.*

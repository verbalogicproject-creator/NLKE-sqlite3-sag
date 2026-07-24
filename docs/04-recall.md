# 04 — Recall: BM25 + structural over your own journal

`SagJournal.recall()` doesn't index anything external — it searches the
journal itself. Every entry you `remember()` and every fact you
`record_fact()` becomes searchable the moment it's written, via
`declared_core`'s hybrid retrieval engine
(`sqlite3_sag/query.py::SagJournal.recall` → `declared_core.hybrid_query`).

This chapter builds on `examples/recall_over_journal.py` — run it alongside
reading this.

## What recall() actually calls

```python
def _run(self, text, *, limit, table, use_intent):
    result = hybrid_query(text, self.corpus, self.conn,
                           limit=fetch, dense=None, use_intent=use_intent)
```

Note `dense=None` — it's **hardcoded**, not a parameter you can set on
`SagJournal.recall()`. This is the concrete shape of what the README calls
"the $0 lexical + structural floor": in this version, the journal's own
recall path never wires a dense (embedding) index. Dense retrieval exists in
`declared_core` (`declared_core.retrieval.dense.NumpyVectorIndex`,
`declared_core.hybrid_query(..., dense=your_index)`), and `declared_core`'s
own CLI demonstrates it (`declared_core/cli.py --dense`) — but it is not
exposed through `SagJournal`. See ROADMAP.md for wiring it as an opt-in
booster.

## The four signals `hybrid_query` fuses

(`declared_core/retrieval/fusion.py::hybrid_query`)

1. **BM25** (`declared_core/retrieval/bm25.py`) — lexical search over each
   declared source's FTS5 index. `JournalSchema.episode_source()` declares
   `content` as the text column; `JournalSchema.fact_source()` declares
   `claim, reason`.
2. **Structural expansion** (`declared_core/retrieval/structural.py`) — given
   the BM25 top-N as anchors, pull rows one hop away via:
   - `cluster_columns` — rows sharing a scalar value (`episode_source()`
     declares `("kind", "batch")`)
   - `tag_columns` — rows whose JSON `tags` arrays overlap (`("tags",)` on
     both sources)
   - `links` — children referencing a matched parent
     (`JournalSchema.fact_link()`: `Link(child="facts", parent="episodes",
     key="source_episode_id")`)
3. **Rules** (`declared_core/dimensions`) — a deterministic, explainable
   12-dimension scorer (`declared_core.dimensions.DEFAULT`) — no model, every
   score in `[0, 1]` and traceable to a plain-Python function
   (`declared_core/dimensions/scorer.py`).
4. **Dense** — always `[]` via `SagJournal.recall()` (see above).

## Structural expansion finds what lexical search can't

```python
j.remember("we chose SQLite over Postgres for the journal store",
           kind="decision", tags=["storage"])
j.remember("the FTS5 trigger fires once per insert, not once per row change",
           kind="gotcha", tags=["storage", "fts5"])
j.remember("retrieval 'sqlite storage' -> notes on the journal store [bm25]",
           kind="sag.retrieval", tags=["storage", "declared-grep", "bm25"])

j.recall("storage")
# -> 3 hits: the sag.retrieval entry (literal BM25 match on "storage"),
#    PLUS the decision and gotcha entries — found via the shared "storage"
#    tag, even though neither one's CONTENT contains the word "storage".
```

That's the point of structural expansion: it surfaces relevant rows that
share *no query terms* with the question at all.

## Intent-adaptive fusion

`declared_core.classify_intent(query)` reads the query text with a small
regex table (`declared_core/retrieval/intent.py`) and picks one of eight
intents, each mapping to different `(bm25, structural, rules, dense)` fusion
weights:

```python
from declared_core import classify_intent

classify_intent('"sqlite" exact')            # -> exact_match (conf 0.90) — up-weights bm25
classify_intent("how do I configure the store")  # -> workflow (conf 0.90) — up-weights structural
classify_intent("tell me about storage")      # -> exploratory (conf 0.60) — up-weights dense/structural
```

Nothing here is learned — it's a declared, auditable regex → weight table.
`recall(use_intent=False)` disables routing and falls back to classic
(unweighted) RRF.

## Fusion strategy: RRF vs weighted-sum

Below `schema.small_corpus_threshold` (default 100) total candidates,
`hybrid_query` fuses with intent-weighted **reciprocal rank fusion** —
rank-only, robust when BM25/structural/rules scores live on different
scales. At or above the threshold it switches to a cheaper **weighted-sum**
(`declared_core/retrieval/fusion.py::_weighted_sum`). A brand-new journal is
always well under 100 candidates, so you'll see `mode: 'rrf'` in practice.

## Facts link back to episodes

```python
j.record_fact("the journal store is SQLite, chosen over Postgres",
               source_episode_id="<the decision entry's id>")
```

A fact hit carries `source_episode_id`, and the structural-expansion link
(`fact_link()`) means a query that anchors on the source episode can also
pull in the crystallized fact — and vice versa.

## Verify your build

```bash
python examples/recall_over_journal.py
#   lexical query -> 4 hit(s), decision entry found
#   'storage' query -> 3 hit(s), kinds=['decision', 'gotcha', 'sag.retrieval'] ...
#   fact hit carries source_episode_id=dddddddddddddddddddddddddddddddd
#   classify_intent('"sqlite" exact') -> exact_match (conf 0.90)
#   ...
# Verify your build: ok

pytest -q -k recall
```

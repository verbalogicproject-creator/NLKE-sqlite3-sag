"""BM25 + structural recall over your own journal -- no dense index required.

``SagJournal.recall()`` delegates to ``declared_core.hybrid_query``: BM25 over
each declared source (episodes + facts), structural expansion one hop out
(shared ``kind``, shared tags, the fact->episode link), an intent classifier
that reweights the fusion per query shape, then reciprocal-rank fusion. This
example seeds a small journal, then shows:

  1. a lexical hit (the query terms are literally in the content)
  2. a structural hit (found via shared ``kind``/tags, not shared words)
  3. how a fact links back to the episode that produced it
  4. the intent classifier picking different fusion weights for different
     query shapes (see PROTOCOL.md is silent on this -- it is a
     `declared_core` behaviour the journal inherits, not part of the wire
     protocol)

Run:  python examples/recall_over_journal.py
Ends with "Verify your build: ok".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from declared_core import classify_intent

from sqlite3_sag import DEFAULT_KINDS, JournalSchema, SagJournal


def main() -> int:
    schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"))
    j = SagJournal.open(":memory:", schema)

    j.remember("we chose SQLite over Postgres for the journal store",
               kind="decision", tags=["storage"], id="d" * 32,
               created_at="2026-01-01T00:00:00+00:00")
    j.remember("the FTS5 trigger fires once per insert, not once per row change",
               kind="gotcha", tags=["storage", "fts5"], id="g" * 32,
               created_at="2026-01-01T00:00:01+00:00")
    j.remember("retrieval 'sqlite storage' -> notes on the journal store [bm25]",
               kind="sag.retrieval", tags=["storage", "declared-grep", "bm25"], id="r" * 32,
               created_at="2026-01-01T00:00:02+00:00")
    j.record_fact("the journal store is SQLite, chosen over Postgres",
                  source_episode_id="d" * 32, id="f" * 32,
                  created_at="2026-01-01T00:00:03+00:00")

    # 1. lexical: "sqlite" and "postgres" are literal terms in the decision entry.
    hits = j.recall("sqlite postgres", limit=5)
    assert any(h["id"] == "d" * 32 for h in hits), hits
    print(f"  lexical query -> {len(hits)} hit(s), decision entry found")

    # 2. structural: "storage" is a literal BM25 hit only in the sag.retrieval
    #    entry's content -- but the decision and gotcha entries share its
    #    "storage" TAG, so structural expansion pulls them in even though
    #    neither's content contains the word "storage".
    hits2 = j.recall("storage", limit=5)
    kinds_found = sorted({h.get("kind") for h in hits2 if h.get("kind")})
    assert "decision" in kinds_found and "gotcha" in kinds_found, kinds_found
    print(f"  'storage' query -> {len(hits2)} hit(s), kinds={kinds_found} "
          f"(decision/gotcha found via shared tag, not shared words)")

    # 3. the fact links back to its source episode via schema.fact_link()
    hits3 = j.recall("journal store chosen", limit=5)
    fact_hit = next((h for h in hits3 if h.get("table") == "facts"), None)
    if fact_hit:
        print(f"  fact hit carries source_episode_id={fact_hit.get('source_episode_id')}")

    # 4. intent classification -- different query shapes route different weights
    #    (bm25, structural, rules, dense), per declared_core/retrieval/intent.py
    for q in ('"sqlite" exact', "how do I configure the store", "tell me about storage"):
        r = classify_intent(q)
        print(f"  classify_intent({q!r}) -> {r.intent} (conf {r.confidence:.2f})")

    print("Verify your build: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

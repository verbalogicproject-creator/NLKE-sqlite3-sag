"""Intent-adaptive fusion weights.

Different questions want different signals. "What's the exact flag for X?" is a
lexical, BM25 job. "How do I set up a pipeline?" wants the structural neighbours
of the matched steps. "Tell me about caching" is a broad, semantic sweep. A
single fixed fusion recipe serves none of them well.

`classify_intent` reads the query with a small, transparent regex table and
picks one of eight intents. Each intent maps to a weight profile over the four
fused signals — **α embedding · β BM25 · γ structural · δ declared** — which the
fusion layer feeds into weighted RRF. Nothing here is learned; the mapping is
declared and auditable, and you can print exactly why a query got its weights.

The four weights correspond to the four ranked lists `hybrid_query` fuses, in
this order: ``(bm25, structural, rules, dense)``.
  - β BM25       → the ``bm25`` list
  - γ structural → the ``structural`` list
  - δ declared   → the ``rules`` (dimension) list
  - α embedding  → the ``dense`` list
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (bm25, structural, rules, dense) — one weight per fused list.
Weights = tuple[float, float, float, float]

# All-equal weights → classic (unweighted) RRF. Used when intent routing is off.
UNIFORM: Weights = (1.0, 1.0, 1.0, 1.0)

INTENT_WEIGHT_PROFILES: dict[str, Weights] = {
    #                    bm25  struct rules dense
    "exact_match":      (1.00, 0.20, 0.40, 0.30),
    "capability_check": (0.85, 0.35, 0.70, 0.45),
    "debugging":        (0.70, 0.60, 0.95, 0.45),
    "workflow":         (0.60, 0.95, 0.60, 0.50),
    "comparison":       (0.60, 0.45, 0.65, 0.85),
    "goal_based":       (0.55, 0.85, 0.60, 0.75),
    "exploratory":      (0.45, 0.75, 0.50, 0.95),
    "semantic":         (0.60, 0.50, 0.55, 0.85),
}

# Ordered most-specific first; first match wins. confidence: 0.9 for a strong
# structural/keyword signal, 0.6 for a softer verb cue.
_INTENT_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("exact_match",      re.compile(r'"[^"]+"|\bexact(ly)?\b|\bverbatim\b|--\w'), 0.9),
    ("debugging",        re.compile(r"\b(error|bug|fail(ing|ed)?|broken|crash|exception|traceback|stack ?trace|debug|regression|why (is|does|isn't|doesn't).*(not|fail))\b", re.I), 0.9),
    ("comparison",       re.compile(r"\b(vs\.?|versus|compare|comparison|difference between|trade-?offs?|better than|instead of)\b", re.I), 0.9),
    ("workflow",         re.compile(r"\b(how (do|to|can) i|how to|steps? to|set up|configure|install|workflow|pipeline|process for)\b", re.I), 0.9),
    ("capability_check", re.compile(r"^\s*(can|does|is|are|could|will|should)\b|\b(able to|support(s|ed)?|capable of|possible to)\b", re.I), 0.85),
    ("goal_based",       re.compile(r"\b(build|create|implement|make|design|add|generate|write|want to|need to)\b", re.I), 0.6),
    ("exploratory",      re.compile(r"\b(explore|overview|survey|tell me about|everything about|list all|show me|what (is|are)|introduc)\b", re.I), 0.6),
]


@dataclass(frozen=True)
class IntentResult:
    """The classified intent, its confidence, and the fusion weights it maps to."""

    intent: str
    confidence: float
    weights: Weights

    def __str__(self) -> str:  # for CLI / debugging
        b, s, r, d = self.weights
        return (f"{self.intent} (conf {self.confidence:.2f}) "
                f"bm25={b} struct={s} rules={r} dense={d}")


def classify_intent(query: str) -> IntentResult:
    """Classify a query into one of eight intents via the regex table.

    Falls back to ``semantic`` (confidence 0.3) when nothing matches — a
    balanced, dense-leaning profile that is a safe default for prose queries.
    """
    text = query or ""
    for intent, pattern, conf in _INTENT_PATTERNS:
        if pattern.search(text):
            return IntentResult(intent, conf, INTENT_WEIGHT_PROFILES[intent])
    return IntentResult("semantic", 0.3, INTENT_WEIGHT_PROFILES["semantic"])


def weights_for(query: str, *, enabled: bool = True) -> Weights:
    """The (bm25, structural, rules, dense) weights for a query.

    ``enabled=False`` returns UNIFORM — classic RRF, no intent routing.
    """
    if not enabled:
        return UNIFORM
    return classify_intent(query).weights


def reallocate_absent(weights: Weights, present: tuple[bool, bool, bool, bool]) -> Weights:
    """Move an absent leg's declared weight to its substitute, instead of losing it.

    THE BUG THIS FIXES. A weight profile is a declared RATIO between four signals.
    When a leg returns nothing, its weight simply stops contributing — and the profile
    silently becomes a *different* profile that nobody declared and no test observes.

    ``exploratory`` is the worst case, and it is the common one, because dense is
    optional by design (invariant 2: "BM25 is the floor"). Declared:

        exploratory     bm25 0.45   struct 0.75   rules 0.50   dense 0.95

    The intent is plainly "lean on semantics." With no embedder the dense list is empty,
    the 0.95 evaporates, and what actually runs is ``struct 0.75`` against ``bm25 0.45``
    — **structural outweighing lexical 1.67x**, which is "lean on structure": a policy
    the author never wrote.

    Measured on a 366-document corpus of near-identical model cards, where structural
    expansion returns the sibling set and is therefore *anti*-discriminating:

        intent routing on, as shipped                recall@4  11/20 = 0.5500
        intent routing off (UNIFORM)                 recall@4  16/20 = 0.8000
        intent routing on + this reallocation        recall@4  16/20 = 0.8000

    Every profile with ``struct/bm25 > 1`` lost flips (exploratory -4, goal_based -1);
    every profile below 1.0 was exactly neutral.

    REPLICATED ON A SECOND, INDEPENDENT CORPUS, and now ESTABLISHED. The first corpus
    gave discordant (5,0), p = 0.0625 — one flip short of the gate. The same intervention
    was then measured on the EU AI Act corpus (12 provisions, 30 queries, a real declared
    edge list wired into the structural leg — a corpus with no near-duplicate siblings and
    a different question set):

        k    corpus 1 (n=20)   corpus 2 (n=30)   pooled    exact McNemar p
        1        (1,0)             (3,0)          (4,0)        0.1250
        2        (3,0)             (3,0)          (6,0)        0.0312
        4        (5,0)             (4,0)          (9,0)        0.0039   <- primary
        8        (2,0)             (2,0)          (4,0)        0.1250

    **22 flips across two corpora and four cutoffs, zero reversals anywhere.**

    recall@4 is the PRE-REGISTERED primary endpoint (it was the metric on corpus 1 from
    the start, matching the answering arm's 4-document context window), so its pooled
    p = 0.0039 needs no multiplicity correction. The other three k values are secondary
    and four were tested, so they do need it: under Benjamini-Hochberg only k=4 survives.
    **k=2's (6,0) is therefore suggestive, NOT established, and is not banked as a claim.**
    Corpus 2 alone is (4,0), p = 0.125 — a replication of direction, not independently
    decisive; the significance comes from pooling. Corpus 2 also has only 12 documents, so
    k=8 there is near-saturated (28/30 -> 30/30) and is the weakest column in the table.

    Two claims, two types, both now settled: the *bug* is existential and was established
    by instrumenting the legs directly; the *recall improvement* is comparative and is
    established at the primary endpoint by the pooled result above.
    Reproduce: ``NLKE-primitives-library/tools/measure_corpus2.py``.

    WHY REALLOCATION AND NOT RENORMALISATION. Renormalising the live weights was tried
    first and is a **no-op**: weighted RRF sums ``w_i / (k + rank_i)``, so scaling every
    live weight by a constant scales every score by that constant and preserves the
    ordering exactly. Only the RATIO can change the result.

    WHY DENSE FALLS BACK TO BM25. They are substitutes — both score a document's OWN
    content, one lexically and one semantically. ``structural`` scores its NEIGHBOURS,
    which is a different question, so it is never a fallback target. ``rules`` is not
    either: a declared-dimension score has no lexical equivalent.

    SCOPE, STATED HONESTLY. Only the dense case is reallocated, and only the dense case
    was measured — the rules leg was non-empty throughout the run above, so a
    rules-fallback would be an unmeasured guess wearing a measured result's clothes.
    An absent ``structural`` or ``rules`` leg still loses its weight; that residue of the
    same bug is left visible rather than fixed blind.

    NO-OP WHEN DENSE IS PRESENT, which is what makes this safe to ship fleet-wide: a
    deployment with an embedder is unaffected, so the intended case cannot regress.

    AND NO-OP FOR AN ALL-EQUAL PROFILE — i.e. ``UNIFORM``, intent routing switched off.
    That is not a special case bolted on; it follows from the principle. This repair
    exists to preserve a declared LEAN when the leg it leans on is missing. ``UNIFORM``
    declares no lean, so dropping its dense weight already leaves ``1:1:1`` — equality
    among the legs that remain, which is exactly what was declared. Reallocating would
    make it ``2:1:1``, inventing a lexical bias nobody asked for and breaking the
    documented contract that intent-off is classic unweighted RRF. Measured before
    exempting it: reallocating UNIFORM changed recall@4 by nothing (16/20 either way) —
    so it would have been an unrequested semantic change bought for zero.
    """
    bm25, struct, rules, dense = weights
    if len(set(weights)) == 1:          # declares no lean; there is nothing to preserve
        return weights
    if not present[3] and dense:
        bm25, dense = bm25 + dense, 0.0
    return (bm25, struct, rules, dense)

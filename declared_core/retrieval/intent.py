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

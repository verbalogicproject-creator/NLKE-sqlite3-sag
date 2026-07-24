"""Generate the conformance fixtures under ``fixtures/`` from the reference
implementation, freezing the canonical hashes as a cross-provider contract.

Run:  python tools/gen_fixtures.py
Then the committed fixtures are the target an external adapter must match, and
``tests/test_conformance.py`` re-derives them to catch any drift in the
canonicalization / hash-chain algorithm.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sqlite3_sag.conformance import run_fixture  # noqa: E402

# §13.1 free-text is NOT normalized. Build genuinely-distinct byte sequences: the
# same word in NFC (é = U+00E9) vs NFD (e + U+0301). A conforming journal must hash
# their raw bytes distinctly; an adapter that NFC-normalizes content would collapse
# them and fail to reproduce the decomposed row's pinned hash.
_COMPOSED = unicodedata.normalize("NFC", "café render")
_DECOMPOSED = unicodedata.normalize("NFD", "café render")
assert _COMPOSED != _DECOMPOSED, "composed and decomposed must differ in bytes"

FIX = REPO / "fixtures"


def _row(id_hex: str, ts: str, kind: str, content: str, **extra):
    d = {"id": id_hex, "created_at": ts, "kind": kind, "content": content}
    d.update(extra)
    return d


TWO_INPUTS = [
    _row("11111111111111111111111111111111", "2026-01-01T00:00:00+00:00",
         "sag.retrieval", "loaded context pack A", tags=["ctx", "load"]),
    _row("22222222222222222222222222222222", "2026-01-01T00:00:01+00:00",
         "sag.context_load", "answered from pack A", tags=[],
         metadata={"k": 1}, session_id="s1"),
]

THREE_INPUTS = TWO_INPUTS + [
    _row("33333333333333333333333333333333", "2026-01-01T00:00:02+00:00",
         "sag.retrieval", "loaded context pack B", tags=["ctx"]),
]

# name -> fixture skeleton (inputs + operations + which verify fields to pin)
SKELETONS = {
    "basic_two_rows": {
        "name": "basic_two_rows",
        "description": "Two clean chained rows; verify ok. Pins the canonical row hashes.",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": TWO_INPUTS,
        "_pin_verify": ("ok", "break", "checked", "unchained", "head_hash"),
    },
    "idempotent_reinsert": {
        "name": "idempotent_reinsert",
        "description": "A duplicate id is a no-op: one row, chain unadvanced, verify ok.",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": [
            _row("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "2026-01-01T00:00:00+00:00",
                 "sag.retrieval", "x", tags=[]),
            _row("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "2026-01-01T00:00:09+00:00",
                 "sag.retrieval", "x", tags=[]),
        ],
        "_pin_verify": ("ok", "break", "checked"),
    },
    "tamper_content": {
        "name": "tamper_content",
        "description": "Mutate row 2's content in place -> row-hash-mismatch at seq 2.",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": TWO_INPUTS,
        "tamper": [{"seq": 2, "set": {"content": "answered from pack B"}}],
        "_pin_verify": ("ok", "break", "at_seq", "checked"),
    },
    "sequence_gap": {
        "name": "sequence_gap",
        "description": "Delete the middle row of a 3-row chain -> sequence-gap at seq 2.",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": THREE_INPUTS,
        "delete_seq": [2],
        "_pin_verify": ("ok", "break", "at_seq", "checked"),
    },
    # ── X1 §13 joint-freeze fixtures (frozen with Codex 2026-07-24) ───────────
    "unicode_distinct": {
        "name": "unicode_distinct",
        "description": "§13.1 free-text is NOT normalized: an NFC-composed vs a decomposed "
                       "spelling of the same word are DISTINCT inputs with distinct hashes.",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": [
            _row("d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1", "2026-01-01T00:00:00+00:00",
                 "sag.retrieval", _COMPOSED, tags=[]),    # NFC composed (U+00E9)
            _row("d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2", "2026-01-01T00:00:01+00:00",
                 "sag.retrieval", _DECOMPOSED, tags=[]),  # NFD decomposed (e + U+0301)
        ],
        "_pin_verify": ("ok", "break", "checked"),
    },
    "namespace_scoped": {
        "name": "namespace_scoped",
        "description": "§13.3 ns binds into the hash: the same logical inputs under a "
                       "scope_uri ns hash DIFFERENTLY than the ns='' basic_two_rows fixture.",
        "chain": {"alg": "sha256", "ns": "sag://sag-video/project/demo/project/demo"},
        "inputs": TWO_INPUTS,
        "_pin_verify": ("ok", "break", "checked"),
    },
    "receipt_observation_roundtrip": {
        "name": "receipt_observation_roundtrip",
        "description": "§13.4 frozen sag.receipt + sag.observation metadata field names; "
                       "pins their canonical hashes. A committed receipt is not observed.",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": [
            _row("2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a", "2026-01-01T00:00:00+00:00",
                 "sag.receipt", "receipt render project=demo rev=7 status=committed",
                 tags=["sag.receipt"],
                 metadata={
                     "receipt_id": "rcpt-1", "request_id": "req-1", "command": "render",
                     "status": "committed", "actor": "engine", "project_id": "demo",
                     "project_revision": 7,
                 }),
            _row("0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b", "2026-01-01T00:00:01+00:00",
                 "sag.observation", "observation of rcpt-1 by independent observer",
                 tags=["sag.observation"],
                 metadata={
                     "observation_id": "obs-1", "receipt_id": "rcpt-1",
                     "observer": "verifier", "observer_mode": "independent",
                     "passed": None, "inconclusive": True,
                     "observed_at": "2026-01-01T00:00:01+00:00",
                 }),
        ],
        "_pin_verify": ("ok", "break", "checked", "head_hash"),
    },
    "refuse_float_metadata": {
        "name": "refuse_float_metadata",
        "description": "§13.2 number profile: a nested float in metadata is REFUSED by the "
                       "payload gate (adapters encode fractional values as decimal strings).",
        "chain": {"alg": "sha256", "ns": ""},
        "inputs": [
            _row("f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0", "2026-01-01T00:00:00+00:00",
                 "sag.retrieval", "a score", tags=[], metadata={"scores": {"a": 0.1}}),
        ],
        "_refusal": True,
    },
}


def build(skel: dict) -> dict:
    refusal = skel.pop("_refusal", False)
    pins = skel.pop("_pin_verify", None)
    got = run_fixture(skel)
    if refusal:
        skel["expect_refusal"] = True
        skel["expected"] = {
            "refused": got["refused"],
            "refused_index": got["refused_index"],
            "count": got["count"],
        }
    else:
        verify = {k: got["verify"][k] for k in pins}
        skel["expected"] = {"rows": got["rows"], "verify": verify, "count": got["count"]}
    return skel


def main() -> int:
    FIX.mkdir(exist_ok=True)
    for name, skel in SKELETONS.items():
        fixture = build(skel)
        path = FIX / f"{name}.json"
        path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        exp = fixture["expected"]
        detail = "REFUSED" if exp.get("refused") else f"verify.break={exp.get('verify', {}).get('break')}"
        print(f"wrote {path.relative_to(REPO)}  ({exp['count']} rows, {detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

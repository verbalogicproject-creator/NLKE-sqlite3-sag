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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sqlite3_sag.conformance import run_fixture  # noqa: E402

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
}


def build(skel: dict) -> dict:
    pins = skel.pop("_pin_verify")
    got = run_fixture(skel)
    verify = {k: got["verify"][k] for k in pins}
    skel["expected"] = {"rows": got["rows"], "verify": verify, "count": got["count"]}
    return skel


def main() -> int:
    FIX.mkdir(exist_ok=True)
    for name, skel in SKELETONS.items():
        fixture = build(skel)
        path = FIX / f"{name}.json"
        path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}  ({fixture['expected']['count']} rows, "
              f"verify.break={fixture['expected']['verify'].get('break')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

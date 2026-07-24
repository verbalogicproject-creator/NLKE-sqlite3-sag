"""register-before-emit + refuse-to-pretend, demonstrated end-to-end.

Two independent gates run on every ``remember()`` call, in this order
(see ``sqlite3_sag/ingest.py::remember``):

  1. ``schema.validate_kind(kind)``   -- the kinds gate (register-before-emit)
  2. ``check_payload(content, metadata, ...)`` -- the payload-admissibility gate

Both raise rather than silently mis-recording. This example declares a small
kind vocabulary, appends one legitimate entry, then shows each gate refusing
exactly the input class it is meant to catch.

Run:  python examples/register_before_emit.py
Ends with "Verify your build: ok" when every refusal fires as documented.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlite3_sag import DEFAULT_KINDS, InadmissiblePayload, JournalSchema, SagJournal


def main() -> int:
    # Only these kinds may be appended -- "sag.retrieval" is declared, nothing else is.
    schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"), max_content_bytes=64)
    j = SagJournal.open(":memory:", schema)

    # ── a legitimate entry: the declared kind, small content ────────────────
    r = j.remember("chose sqlite for the journal store", kind="decision")
    assert r["kind"] == "decision"
    print(f"  ok: appended kind=decision id={r['id'][:8]}…")

    # ── gate 1: register-before-emit -- an undeclared kind is refused ───────
    try:
        j.remember("this should never land", kind="video.render")
        raise AssertionError("undeclared kind was NOT refused")
    except ValueError as e:
        print(f"  refused (undeclared kind): {e}")

    # ── gate 2a: refuse-to-pretend -- content over the size cap is refused ──
    try:
        j.remember("x" * 200, kind="decision")  # cap is 64 bytes on this schema
        raise AssertionError("oversize content was NOT refused")
    except InadmissiblePayload as e:
        print(f"  refused (oversize content): {e}")

    # ── gate 2b: refuse-to-pretend -- a credential marker is refused ────────
    j2 = SagJournal.open(":memory:", JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))
    try:
        j2.remember("leaked key: AKIAIOSFODNN7EXAMPLE", kind="decision")
        raise AssertionError("a credential marker was NOT refused")
    except InadmissiblePayload as e:
        print(f"  refused (credential marker): {e}")

    # ── gate 2c: refuse-to-pretend -- a float in metadata is refused ────────
    try:
        j2.remember("ok content", kind="decision", metadata={"confidence": 0.87})
        raise AssertionError("a float in metadata was NOT refused")
    except InadmissiblePayload as e:
        print(f"  refused (float in metadata): {e}")

    # the same value as a string is fine -- the gate objects to the TYPE, not the number
    r2 = j2.remember("ok content", kind="decision", metadata={"confidence": "0.87"})
    assert r2["seq"] == 1
    print("  ok: the same value as a string metadata field is admissible")

    print("Verify your build: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

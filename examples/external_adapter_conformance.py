"""An independent adapter, implemented from PROTOCOL.md alone -- proving the
wire contract, not just this library, is what's conformant.

This does NOT import ``sqlite3_sag.chain``. It re-derives the canonical
preimage and the SHA-256 row hash straight from PROTOCOL.md section 5.1, then
checks the result against the committed ``fixtures/*.json`` byte-for-byte.
This is the shape of the cross-provider promise (the X1-CLAUDE-002 story in
docs/05-conformance-and-provider-neutrality.md): any producer, in any
language, that follows the spec text produces identical hashes -- without
needing this package as a library.

Run:  python examples/external_adapter_conformance.py
Ends with "Verify your build: ok" when both fixtures reproduce.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "fixtures"

# PROTOCOL.md §5: GENESIS = "0" * 64
GENESIS = "0" * 64


def canonical_bytes(obj: object) -> bytes:
    """PROTOCOL.md §5.1: sorted keys, compact separators, UTF-8, no ASCII-escaping."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def row_hash(
    *, ns, seq, prev, id, kind, content, session_id, batch, tags, metadata,
    method, schema_version, created_at,
) -> str:
    """PROTOCOL.md §5.1's preimage object, hashed with SHA-256 (§5)."""
    preimage = {
        "v": 1,
        "ns": ns or "",
        "seq": seq,
        "prev": prev,
        "id": id,
        "kind": kind,
        "content": content,
        "session_id": session_id,
        "batch": batch,
        "tags": tags,
        "metadata": metadata,
        "method": method,
        "schema_version": schema_version,
        "created_at": created_at,
    }
    return hashlib.sha256(canonical_bytes(preimage)).hexdigest()


def walk_fixture(fixture: dict) -> list[dict]:
    """Independently compute (seq, prev_hash, row_hash) for every input, in
    order -- the reference-implementation-free version of ``verify()``'s walk."""
    rows = []
    prev = GENESIS
    ns = fixture.get("chain", {}).get("ns", "")
    for i, inp in enumerate(fixture["inputs"], start=1):
        h = row_hash(
            ns=ns, seq=i, prev=prev, id=inp["id"], kind=inp["kind"],
            content=inp["content"], session_id=inp.get("session_id"),
            batch=inp.get("batch"), tags=inp.get("tags", []),
            # A missing `metadata` on the wire means "no metadata was supplied",
            # which the reference producer stores as `{}` (see ingest.remember:
            # `metadata or {}`) -- the preimage binds `{}`, not `null`.
            metadata=inp.get("metadata") or {}, method=inp.get("method", "manual"),
            schema_version=1, created_at=inp["created_at"],
        )
        rows.append({"seq": i, "prev_hash": prev, "row_hash": h})
        prev = h
    return rows


def main() -> int:
    # Both fixtures share the same two clean inputs; "tamper_content"'s pinned
    # `rows` are the ORIGINAL (pre-tamper) hashes -- the tamper mutates only the
    # stored `content` column, never the `row_hash` column, which is exactly
    # what makes the mismatch detectable. So both are valid targets for a
    # clean, untampered independent walk.
    checked = 0
    for name in ("basic_two_rows", "tamper_content"):
        fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        got = walk_fixture(fixture)
        want = fixture["expected"]["rows"]
        assert got == want, (name, got, want)
        checked += 1
        print(f"  {name}: {len(got)} row(s) match, independently re-derived from PROTOCOL.md alone")

    print(f"Verify your build: ok ({checked} fixtures reproduced from the spec, no sqlite3_sag import)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

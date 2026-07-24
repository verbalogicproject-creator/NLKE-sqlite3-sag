"""Append a few entries, verify the chain, then demonstrate tamper-detection.

Run:  python examples/append_and_verify.py
Ends with "Verify your build: ok" when everything behaves as documented.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlite3_sag import DEFAULT_KINDS, JournalSchema, SagJournal


def main() -> int:
    schema = JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"))
    j = SagJournal.open(":memory:", schema)

    for i in range(3):
        r = j.remember(
            f"retrieval q{i} -> src/mod{i}.py [bm25] score=0.0{i}",
            kind="sag.retrieval",
            tags=["declared-grep", "bm25"],
            id=f"{i:032d}",
            created_at=f"2026-01-01T00:00:0{i}+00:00",
        )
        print(f"  appended seq={r['seq']} row_hash={r['row_hash'][:12]}…")

    v = j.verify()
    assert v["ok"] and v["checked"] == 3, v
    print(f"  chain ok: {v['checked']} entries, head={v['head_hash'][:12]}…")

    # recall over the journal itself
    hits = j.recall("retrieval", limit=3)
    print(f"  recall('retrieval') -> {len(hits)} hits")

    # tamper: mutate an entry directly; the chain must catch it
    j.conn.execute("UPDATE episodes SET content='forged' WHERE seq=2")
    vt = j.verify()
    assert vt["break"] == "row-hash-mismatch" and vt["at_seq"] == 2, vt
    print(f"  tamper detected: {vt['break']} at seq {vt['at_seq']}")

    print("Verify your build: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

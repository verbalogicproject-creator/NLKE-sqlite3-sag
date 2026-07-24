"""Stage-1 green bar for sqlite3-sag:

(a) extraction parity  — the two shipped consumers' exact pattern runs unchanged
(b) chain + verify     — append N, verify ok, seq monotonic, head stable
(c) tamper             — every break class is detected + classified
(d) idempotency        — a duplicate id is a no-op, chain unadvanced
(e) degradation        — chain-disabled still appends; recall works; payload gate
(f) hmac + old-db      — keyed mode; in-place migration of a pre-chain database
"""

from __future__ import annotations

import sqlite3

import pytest

from sqlite3_sag import (
    DEFAULT_KINDS,
    InadmissiblePayload,
    JournalSchema,
    SagJournal,
)

TS0 = "2026-01-01T00:00:00+00:00"


def _ts(n: int) -> str:
    return f"2026-01-01T00:00:{n:02d}+00:00"


# ── (a) extraction parity: the two consumers' literal pattern ────────────────
def test_consumer_pattern_declared_grep_unchanged():
    # Verbatim shape of declared_grep/receipt.py::journal_sag
    from project_memory import DEFAULT_KINDS as DK, MemorySchema, ProjectMemory

    SAG_KIND = "sag.retrieval"
    schema = MemorySchema(kinds=(*DK, SAG_KIND))
    mem = ProjectMemory.open(":memory:", schema)
    res = mem.remember(
        "retrieval 'auth flow' -> src/login.py [bm25] score=0.0313",
        kind=SAG_KIND,
        tags=["declared-grep", "retrieval", "bm25"],
    )
    assert res["id"] and res["kind"] == SAG_KIND and res["fact_id"] is None
    assert mem.count()["episodes"] == 1
    assert mem.verify()["ok"] is True


def test_consumer_pattern_declared_context_unchanged():
    from project_memory import DEFAULT_KINDS as DK, MemorySchema, ProjectMemory

    SAG_KIND = "sag.context_load"
    schema = MemorySchema(kinds=(*DK, SAG_KIND))
    mem = ProjectMemory.open(":memory:", schema)
    mem.remember(
        "context_load 'fix bug' kept src/x.py#f [weighted] score=0.5000 tokens=120",
        kind=SAG_KIND,
        tags=["declared-context", "kept", "weighted"],
    )
    assert mem.count()["episodes"] == 1
    assert mem.verify()["ok"] is True


def test_unknown_kind_is_refused_register_before_emit():
    j = SagJournal.open(":memory:")
    with pytest.raises(ValueError):
        j.remember("x", kind="sag.retrieval")  # not declared


# ── (b) chain + verify ───────────────────────────────────────────────────────
def _journal(**schema_kw) -> SagJournal:
    return SagJournal.open(
        ":memory:", JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"), **schema_kw)
    )


def test_chain_is_monotonic_and_verifies():
    j = _journal()
    hashes = []
    for i in range(5):
        r = j.remember(f"entry {i}", kind="sag.retrieval", id=f"{i:032d}", created_at=_ts(i))
        assert r["seq"] == i + 1
        hashes.append(r["row_hash"])
    v = j.verify()
    assert v["ok"] and v["checked"] == 5 and v["unchained"] == 0
    assert v["head_hash"] == hashes[-1] == j.head_hash()
    # each prev_hash points at the predecessor row_hash
    rows = list(j.conn.execute("SELECT seq, prev_hash, row_hash FROM episodes ORDER BY seq"))
    assert rows[0][1] == "0" * 64
    for k in range(1, 5):
        assert rows[k][1] == rows[k - 1][2]


# ── (c) tamper: all break classes ────────────────────────────────────────────
def _seed_three(j: SagJournal):
    for i in range(3):
        j.remember(f"entry {i}", kind="sag.retrieval", id=f"{i:032d}", created_at=_ts(i))


def test_tamper_content_row_hash_mismatch():
    j = _journal()
    _seed_three(j)
    j.conn.execute("UPDATE episodes SET content=? WHERE seq=2", ("TAMPERED",))
    v = j.verify()
    assert v["break"] == "row-hash-mismatch" and v["at_seq"] == 2 and v["checked"] == 1


def test_tamper_prev_hash_predecessor_mismatch():
    j = _journal()
    _seed_three(j)
    j.conn.execute("UPDATE episodes SET prev_hash=? WHERE seq=2", ("de" * 32,))
    v = j.verify()
    assert v["break"] == "predecessor-mismatch" and v["at_seq"] == 2


def test_delete_row_sequence_gap():
    j = _journal()
    _seed_three(j)
    j.conn.execute("DELETE FROM episodes WHERE seq=2")
    v = j.verify()
    assert v["break"] == "sequence-gap" and v["at_seq"] == 2 and v["checked"] == 1


# ── (d) idempotency ──────────────────────────────────────────────────────────
def test_duplicate_id_is_noop_chain_unadvanced():
    j = _journal()
    a = j.remember("x", kind="sag.retrieval", id="a" * 32, created_at=TS0)
    b = j.remember("x", kind="sag.retrieval", id="a" * 32, created_at=_ts(9))
    assert a["seq"] == 1
    assert "seq" not in b  # ignored insert reports no chain advance
    assert j.count()["episodes"] == 1
    assert j.verify()["ok"] and j.verify()["checked"] == 1


def test_distinct_ids_same_content_are_two_entries():
    j = _journal()
    j.remember("the build broke", kind="sag.retrieval", id="1" * 32, created_at=TS0)
    j.remember("the build broke", kind="sag.retrieval", id="2" * 32, created_at=_ts(1))
    assert j.count()["episodes"] == 2 and j.verify()["ok"]


# ── (e) degradation + payload gate ───────────────────────────────────────────
def test_chain_disabled_still_appends_and_verifies_trivially():
    j = _journal(hash_chain=False)
    r = j.remember("x", kind="sag.retrieval")
    assert "seq" not in r  # unchained row
    j.remember("y", kind="sag.retrieval")
    v = j.verify()
    assert v["ok"] and v["checked"] == 0 and v["unchained"] == 2


def test_recall_works_bm25_structural():
    j = _journal()
    j.remember("we chose sqlite over postgres for the journal", kind="decision")
    j.remember("the fts trigger fired once per insert", kind="gotcha")
    hits = j.recall("sqlite journal", limit=5)
    assert isinstance(hits, list) and len(hits) >= 1
    assert all("rrf_sources" in h or "rrf_score" in h for h in hits)


def test_payload_gate_rejects_oversize_secret_and_float():
    j = _journal(max_content_bytes=32)
    with pytest.raises(InadmissiblePayload):
        j.remember("x" * 64, kind="sag.retrieval")  # over the cap
    j2 = _journal()
    with pytest.raises(InadmissiblePayload):
        j2.remember("AKIAIOSFODNN7EXAMPLE key leak", kind="sag.retrieval")  # secret marker
    with pytest.raises(InadmissiblePayload):
        j2.remember("ok", kind="sag.retrieval", metadata={"score": 0.5})  # float in metadata


def test_normal_consumer_content_is_admissible():
    j = _journal()
    # exactly the shape the shipped consumers emit — must NOT trip the gate
    j.remember("retrieval 'x' -> a.py [bm25,vec] score=0.0313", kind="sag.retrieval",
               tags=["declared-grep", "bm25"], metadata={"tokens": 120, "kept": True})
    assert j.verify()["ok"]


# ── (f) hmac keyed mode + old-db migration ───────────────────────────────────
def test_hmac_mode_requires_key_and_verifies_with_it():
    j = SagJournal.open(
        ":memory:",
        JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"), hash_alg="hmac-sha256"),
        hash_key="s3cret",
    )
    j.remember("keyed entry", kind="sag.retrieval", id="1" * 32, created_at=TS0)
    assert j.verify()["ok"]  # uses the journal's key
    assert j.verify(key="wrong-key")["break"] == "row-hash-mismatch"


def test_hmac_without_key_raises():
    j = SagJournal.open(
        ":memory:",
        JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval"), hash_alg="hmac-sha256"),
    )
    with pytest.raises(ValueError):
        j.remember("keyed entry", kind="sag.retrieval")


_OLD_DDL = """
CREATE TABLE episodes (
  id TEXT PRIMARY KEY, content TEXT NOT NULL, kind TEXT NOT NULL,
  session_id TEXT, batch TEXT, tags TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}',
  method TEXT DEFAULT 'manual', schema_version INTEGER DEFAULT 1, created_at TEXT NOT NULL
)"""


def test_old_db_without_chain_columns_is_migrated_in_place(tmp_path):
    db = tmp_path / "old.db"
    raw = sqlite3.connect(db)
    raw.execute(_OLD_DDL)
    raw.execute(
        "INSERT INTO episodes (id, content, kind, created_at) VALUES (?,?,?,?)",
        ("old1", "a pre-chain entry", "general", TS0),
    )
    raw.commit()
    raw.close()

    j = SagJournal.open(str(db), JournalSchema(kinds=(*DEFAULT_KINDS, "sag.retrieval")))
    # the pre-existing row is unchained; a new append is chained from genesis
    j.remember("a post-migration entry", kind="sag.retrieval", id="1" * 32, created_at=_ts(1))
    v = j.verify()
    assert v["ok"] and v["checked"] == 1 and v["unchained"] == 1
    assert j.count()["episodes"] == 2
    j.close()

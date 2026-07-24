"""Conformance harness — the cross-provider hash-parity contract.

A *fixture* declares a sequence of journal inputs (with pinned ids/timestamps),
an optional tamper/delete, and the expected result: each chained row's
``seq``/``prev_hash``/``row_hash`` + the expected :func:`verify` outcome. Because
the canonical serialization does not bind the physical table name, **identical
declared inputs must produce byte-identical hashes across implementations** — so
an external producer (e.g. the SAG Video side) proves interop by running the same
fixtures through its own adapter and matching the same expected values.

This module is the reference *writer*. An external adapter provides its own
``writer(fixture) -> RunResult``-shaped callable and asserts equality with the
fixture's ``expected`` block. Run the shipped fixtures with :func:`run_fixture`
(the reference writer) and compare with :func:`check_fixture`.

Fixture JSON shape::

    {
      "name": "basic_two_rows",
      "chain": {"alg": "sha256", "ns": ""},
      "inputs": [ {id, created_at, kind, content, tags?, metadata?,
                   session_id?, batch?, method?}, ... ],
      "tamper":    [ {"seq": N, "set": {"column": value}} ],   # optional
      "delete_seq": [N, ...],                                   # optional
      "expected": { "rows": [{seq, prev_hash, row_hash}], "verify": {...}, "count": N }
    }
"""

from __future__ import annotations

from typing import Any, Callable

from .payload import InadmissiblePayload
from .query import SagJournal
from .schema import DEFAULT_KINDS, JournalSchema

RunResult = dict  # {"rows": [ {seq, prev_hash, row_hash} ], "verify": {...}, "count": int}


def _kinds_for(inputs: list[dict[str, Any]]) -> tuple[str, ...]:
    extra = [i["kind"] for i in inputs if i.get("kind") and i["kind"] not in DEFAULT_KINDS]
    seen: list[str] = []
    for k in extra:
        if k not in seen:
            seen.append(k)
    return (*DEFAULT_KINDS, *seen)


def run_fixture(fixture: dict[str, Any], *, hash_key: Any = None) -> RunResult:
    """Run a fixture through the reference writer; return its observable result.

    Deterministic: every input pins ``id`` and ``created_at``. Uses an in-memory
    database, so it is side-effect free.
    """
    inputs = fixture["inputs"]
    chain = fixture.get("chain", {})
    schema = JournalSchema(
        kinds=_kinds_for(inputs),
        hash_alg=chain.get("alg", "sha256"),
        ns=chain.get("ns", ""),
    )
    j = SagJournal.open(":memory:", schema, hash_key=hash_key)
    refused = False
    refused_index: int | None = None
    for idx, i in enumerate(inputs):
        try:
            j.remember(
                i["content"],
                kind=i.get("kind", "general"),
                tags=i.get("tags", []),
                metadata=i.get("metadata"),
                session_id=i.get("session_id"),
                batch=i.get("batch"),
                method=i.get("method", "manual"),
                id=i["id"],
                created_at=i["created_at"],
            )
        except InadmissiblePayload:
            # A refusal fixture asserts the payload gate rejects this input. Record
            # it and stop — the refused entry never enters the chain.
            refused = True
            refused_index = idx
            break

    for t in fixture.get("tamper", []):
        for col, val in t["set"].items():
            j.conn.execute(
                f"UPDATE {schema.episode_table} SET {col} = ? WHERE seq = ?",
                (val, t["seq"]),
            )
    for seq in fixture.get("delete_seq", []):
        j.conn.execute(f"DELETE FROM {schema.episode_table} WHERE seq = ?", (seq,))

    rows = [
        {"seq": r[0], "prev_hash": r[1], "row_hash": r[2]}
        for r in j.conn.execute(
            f"SELECT seq, prev_hash, row_hash FROM {schema.episode_table} "
            f"WHERE seq IS NOT NULL ORDER BY seq ASC"
        )
    ]
    result: RunResult = {
        "rows": rows,
        "verify": j.verify(key=hash_key),
        "count": j.count()["episodes"],
        "refused": refused,
        "refused_index": refused_index,
    }
    j.close()
    return result


def _verify_matches(got: dict[str, Any], expected: dict[str, Any]) -> bool:
    # Compare only the fields the fixture pins (so a fixture need not enumerate all).
    return all(got.get(k) == v for k, v in expected.items())


def check_fixture(fixture: dict[str, Any], *, hash_key: Any = None) -> list[str]:
    """Run a fixture and return a list of human-readable mismatches ([] == pass)."""
    exp = fixture["expected"]
    got = run_fixture(fixture, hash_key=hash_key)
    errors: list[str] = []

    if "refused" in exp and got["refused"] != exp["refused"]:
        errors.append(f"refused: expected {exp['refused']}, got {got['refused']}")
    if "refused_index" in exp and got["refused_index"] != exp["refused_index"]:
        errors.append(f"refused_index: expected {exp['refused_index']}, got {got['refused_index']}")

    if "count" in exp and got["count"] != exp["count"]:
        errors.append(f"count: expected {exp['count']}, got {got['count']}")

    if "rows" in exp:
        if len(got["rows"]) != len(exp["rows"]):
            errors.append(f"row-count: expected {len(exp['rows'])}, got {len(got['rows'])}")
        for want, have in zip(exp["rows"], got["rows"]):
            for k in ("seq", "prev_hash", "row_hash"):
                if want.get(k) != have.get(k):
                    errors.append(
                        f"row seq={want.get('seq')}: {k} expected {want.get(k)!r}, got {have.get(k)!r}"
                    )

    if "verify" in exp and not _verify_matches(got["verify"], exp["verify"]):
        errors.append(f"verify: expected⊇{exp['verify']}, got {got['verify']}")

    return errors

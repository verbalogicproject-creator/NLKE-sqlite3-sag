"""Conformance: every committed fixture must reproduce byte-for-byte.

This is the cross-provider hash-parity contract. The reference writer re-derives
each fixture's rows + verify outcome; any drift in the canonical serialization or
the hash-chain algorithm breaks these tests. An external adapter (e.g. SAG Video)
proves interop by matching the SAME committed ``expected`` values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sqlite3_sag.conformance import check_fixture

FIXTURES = sorted((Path(__file__).resolve().parent.parent / "fixtures").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_reproduces(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    errors = check_fixture(fixture)
    assert not errors, f"{path.name} mismatches:\n" + "\n".join(errors)


def test_there_are_fixtures():
    assert FIXTURES, "no conformance fixtures found under fixtures/"

#!/usr/bin/env bash
# Standalone-install verification for sqlite3-sag — proves the repo is
# genuinely self-contained: it installs and passes its own suite in a FRESH
# venv, with the canonical sibling package (declared_core) provably ABSENT —
# only this repo's own vendored top-level copy satisfies that import.
#
# Usage: tools/verify_standalone.sh   (run from anywhere; the repo root is
#                                       computed from this script's location)
#
# Three independent parts:
#
#  A) THE WHEEL — install in a FRESH venv with NO system-site-packages, from a
#     NEUTRAL cwd with PYTHONPATH unset, then: non-editable install must
#     SUCCEED (no unresolved sibling PyPI dependency), and sqlite3_sag +
#     project_memory + declared_core must import from the venv (proves the
#     vendored code shipped in the install, not from some accidental sibling
#     on disk).
#
#  B) THE $0 FLOOR — the same wheel, WITHOUT numpy installed, must still
#     import and run: the hash chain, append/verify, and BM25+structural
#     recall are pure stdlib. This is the no-numpy proof, not a relaxed check.
#
#  C) THE SUITE — run the repo's own tests at the repo root (fixtures are
#     repo-relative) with PYTHONPATH unset, so sys.path[0] is the repo itself
#     — which holds the vendored copy — and no canonical sibling package is
#     separately pip-installed.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENDORED=(declared_core)
SCRATCH_BASE="${SCRATCH_DIR:-${TMPDIR:-/tmp}/sqlite3-sag-standalone}"
VENV="$SCRATCH_BASE/venv"
WORK="$SCRATCH_BASE/work"
PY="$VENV/bin/python"

echo "===================================================================="
echo "STANDALONE VERIFY: sqlite3-sag   vendored=[${VENDORED[*]}]"
echo "===================================================================="

rm -rf "$SCRATCH_BASE"; mkdir -p "$WORK"
python3 -m venv "$VENV"
"$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1

# ---- Part A: the wheel -------------------------------------------------------
echo "-- [A] pip install (non-editable)  sqlite3-sag[dev]"
if ! "$PY" -m pip install --quiet "${REPO_DIR}[dev]"; then
  echo "FAIL: pip install sqlite3-sag[dev] failed — an unresolved sibling dependency still declared?"
  exit 1
fi

echo "-- [A] wheel probe: origin (neutral cwd, PYTHONPATH unset)"
( cd "$WORK" && unset PYTHONPATH && "$PY" - sqlite3_sag project_memory "${VENDORED[@]}" <<'PYEOF'
import importlib, sys
venv = sys.prefix
bad = []
for name in sys.argv[1:]:
    try:
        m = importlib.import_module(name)
    except Exception as e:                                    # noqa
        print(f"  BAD  import {name:20s} -> ERROR {e!r}"); bad.append(name); continue
    f = getattr(m, "__file__", "") or ""
    in_venv = f.startswith(venv)                              # canonical repo can't start with the venv
    print(f"  {'OK ' if in_venv else 'BAD'}  import {name:20s} -> {f}")
    if not in_venv:
        bad.append(name)
if bad:
    print("FAIL: not loaded from the installed wheel:", ", ".join(bad)); sys.exit(1)
print("  wheel probe: PASS")
PYEOF
) || exit 1

# ---- Part B: the $0 floor (no numpy) -----------------------------------------
echo "-- [B] \$0 floor probe: append + verify + recall with NO numpy installed"
if "$PY" -m pip show numpy >/dev/null 2>&1; then
  echo "  ! numpy unexpectedly present in this venv — uninstalling to prove the floor"
  "$PY" -m pip uninstall --quiet -y numpy >/dev/null 2>&1
fi
( cd "$WORK" && unset PYTHONPATH && "$PY" - <<'PYEOF'
import sys
try:
    import numpy  # noqa: F401
    print("FAIL: numpy is importable — the $0 floor is not being exercised")
    sys.exit(1)
except ImportError:
    pass

import sqlite3_sag
print(f"  sqlite3_sag {sqlite3_sag.__version__} imported with no numpy present")

schema = sqlite3_sag.JournalSchema(kinds=(*sqlite3_sag.DEFAULT_KINDS, "sag.retrieval"))
j = sqlite3_sag.SagJournal.open(":memory:", schema)
j.remember("floor check entry", kind="sag.retrieval", tags=["floor"])
v = j.verify()
assert v["ok"] and v["checked"] == 1, v
hits = j.recall("floor")
print(f"  append+verify ok, recall('floor') -> {len(hits)} hit(s)")
print("  $0 floor probe: PASS")
PYEOF
) || exit 1

# ---- Part C: the suite --------------------------------------------------------
echo "-- [C] pytest (repo tree, vendored copy on path, still no numpy, no separate sibling install)"
( cd "$REPO_DIR" && unset PYTHONPATH && "$PY" -m pytest -q )
rc=$?
echo "===================================================================="
if [ $rc -eq 0 ]; then echo "STANDALONE VERIFY: sqlite3-sag  => PASS"; else echo "STANDALONE VERIFY: sqlite3-sag  => FAIL (pytest rc=$rc)"; fi
echo "===================================================================="
exit $rc

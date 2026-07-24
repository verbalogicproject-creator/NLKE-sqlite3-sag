# Contributing to sqlite3-sag

## Before you start

Read `CLAUDE.md` first — it lists the load-bearing invariants (register-
before-emit fails loud, the hash chain covers `episodes` only, the $0 floor
needs no numpy, `declared_core` is vendored not hand-edited, fixtures are
generated not hand-edited) that CI enforces. Most contribution mistakes are
violations of one of those, not logic bugs.

## Setup

```bash
git clone <this repo>
cd sqlite3-sag
pip install -e ".[dev]"     # runtime deps are zero; [dev] adds pytest
```

Requires Python `>=3.10` (`pyproject.toml`).

## The change loop

```bash
pytest -q                              # 25 tests must pass
python -m compileall -q sqlite3_sag project_memory tests examples tools
python tools/revendor.py check         # declared_core/ must be untouched
python tools/gen_fixtures.py && git diff --exit-code fixtures/   # fixtures must regenerate as a no-op
python examples/append_and_verify.py   # ends "Verify your build: ok"
```

This is exactly `.github/workflows/ci.yml`'s job, run locally, in order. If
any step here fails, CI will fail the same way — fix it before opening a PR.

## If your change touches the hash chain or the canonical serialization

`sqlite3_sag/chain.py` and `sqlite3_sag/conformance.py` are the two modules
where a change can silently break cross-provider hash parity. After editing
either:

```bash
python tools/gen_fixtures.py
git diff fixtures/
```

If the diff is non-empty, one of two things is true: either you made a
deliberate, protocol-level change to the canonical serialization or hash
algorithm (in which case: update `PROTOCOL.md` in the same PR, bump
`PROTOCOL_VERSION` if the change is not backward-compatible, and explain the
diff in your PR description), or you introduced unintended drift (in which
case: fix it, the fixtures should NOT change). A silent, unexplained fixture
diff will not be merged.

## If your change touches `declared_core/`

Don't hand-edit it. `declared_core/` is a vendored, byte-identical copy of a
sibling package (see `VENDORED.json` + `tools/revendor.py`'s module
docstring for why). `python tools/revendor.py check` will fail on a
hand-edited copy — that's the point, it's a supply-chain drift guard, not a
formatting nit. If `declared_core` genuinely needs a fix, make it in the
canonical repo and re-vendor.

## If your change adds a new public symbol

Add it to `sqlite3_sag.__all__` (`sqlite3_sag/__init__.py`) if it's meant to
be part of the public API, and add it to `docs/08-api-reference.md`'s
symbol tables. The API reference chapter asserts (as a runnable snippet)
that `len(sqlite3_sag.__all__)` and `sorted(sqlite3_sag.__all__)` match what
the prose documents — an undocumented public symbol or a documented-but-
missing one is a doc bug, not just an omission.

## If your change adds a dependency

Runtime `dependencies` in `pyproject.toml` must stay `[]`. A new capability
that needs a third-party package belongs in
`[project.optional-dependencies]` as a new, clearly-named extra (follow the
shape of the existing `dense` extra), never in the base install. Run
`tools/verify_standalone.sh` to confirm the $0 floor (no numpy, no
non-stdlib import) still holds.

## If your change touches docs

Every capability claim, count, path, command output, and API name in
`README.md` / `docs/` / `HOW-TO-USE.md` must be something you actually ran
against this checkout. If you can't verify a claim, don't add it — this
repo's documentation discipline is grounding-first (see the "Verify your
build" section closing every chapter in `docs/`).

## Style

- No new runtime dependency without an explicit extra (above).
- Docstrings explain *why*, not just *what* — see any existing module for
  the tone (e.g. `sqlite3_sag/chain.py`'s module docstring explains the two
  honest security-envelope limits, not just the function signatures).
- Tests live in `tests/`; conformance fixtures live in `fixtures/` and are
  generated, not hand-written (above).
- Keep the register-before-emit and refuse-to-pretend gates fail-loud
  (`raise`, not a logged warning and a silent continue).

## License and attribution

Apache-2.0 (`LICENSE`, `NOTICE`). Authored by Eyal Nof. Contributions are
accepted under the same license.

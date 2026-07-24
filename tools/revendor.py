#!/usr/bin/env python3
"""Re-vendor + drift-guard for sqlite3-sag's Option-A vendored package.

sqlite3-sag composes one proven, Apache-2.0 sibling package (``declared_core``,
the BM25 + structural + RRF retrieval engine the journal's ``recall()`` runs
on) by carrying a byte-identical top-level copy of it — so this repo installs
and runs on its own, in its own environment, with no ``PYTHONPATH`` coupling
and no unpublished PyPI dependency. ``declared_core`` appears exactly once.

This tool owns both directions:

  check   the drift guard, fully standalone (no canonical source needed): for
          every entry recorded in VENDORED.json, recompute the on-disk copy's
          tree hash and compare it to the hash recorded at the last sync.
          Mismatch => TAMPER (the copy was hand-edited after vendoring).

  sync    the maintainer-only refresh: pass --canonical-root <path> pointing
          at the monorepo that holds the canonical ``declared_core`` package
          as a sibling (e.g. .../projects), and this re-copies it from there
          and rewrites VENDORED.json. Requires --canonical-root explicitly —
          there is no default, so this tool never bakes in one machine's
          absolute path.

Stdlib only. Deterministic and byte-stable (no timestamps, sorted walks, fixed
JSON formatting), so a clean copy always satisfies
``diff -r <repo>/declared_core <canonical>/declared_core`` with no output.

Run from the repo root:  python tools/revendor.py {check,sync}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAMP = REPO_ROOT / "VENDORED.json"
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")

# name -> the package's own directory, RELATIVE TO the canonical monorepo root
# (--canonical-root). declared_core's canonical repo nests its own package at
# "declared_core/declared_core" (repo dir / package dir), same layout every
# sibling consumer in this family points at — so a hash computed here is
# directly comparable to the one recorded in a sibling's VENDORED.json.
SOURCES: dict[str, str] = {
    "declared_core": "declared_core/declared_core",
}


def _iter_files(pkg_dir: Path):
    """Yield (relative_posix_path, absolute_path) for every real file under
    pkg_dir, excluding compiled bytecode. Deterministically sorted."""
    files = []
    for p in pkg_dir.rglob("*"):
        if p.is_dir():
            continue
        if "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo"):
            continue
        files.append((p.relative_to(pkg_dir).as_posix(), p))
    files.sort(key=lambda t: t[0])
    return files


def tree_sha(pkg_dir: Path) -> str:
    """blake2b over the whole package tree (paths + bytes), byte-stable.

    Same algorithm the canonical fleet's tools/revendor.py uses, so a hash
    computed here is directly comparable to the one recorded in a sibling
    consumer's VENDORED.json (e.g. declared-grep's or project_memory's
    recorded hash for declared_core) as an independent fidelity check.
    """
    h = hashlib.blake2b(digest_size=32)
    for rel, path in _iter_files(pkg_dir):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return "blake2b:" + h.hexdigest()


def _read_version(pkg_dir: Path) -> str:
    import re

    version_re = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")
    for candidate in ("_version.py", "__init__.py"):
        f = pkg_dir / candidate
        if f.exists():
            m = version_re.search(f.read_text(encoding="utf-8"))
            if m:
                return m.group(1)
    return "unknown"


def _dump_stamp(entries: list[dict]) -> str:
    payload = {"vendored": sorted(entries, key=lambda e: e["name"])}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def sync(canonical_root: Path) -> int:
    entries = []
    for name, rel_src in sorted(SOURCES.items()):
        src = canonical_root / rel_src
        if not src.is_dir():
            print(f"  ! {name}: source not found at {src}", file=sys.stderr)
            return 1
        dest = REPO_ROOT / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=_IGNORE)
        sha = tree_sha(dest)
        entries.append(
            {
                "name": name,
                "source_version": _read_version(dest),
                "tree_sha": sha,
                "generated_by": "tools/revendor.py",
            }
        )
        print(f"  + {name}  {sha[:19]}…  v{entries[-1]['source_version']}")
    STAMP.write_text(_dump_stamp(entries), encoding="utf-8")
    print(f"\nwrote {STAMP.relative_to(REPO_ROOT)}")
    return 0


def check() -> int:
    if not STAMP.exists():
        print(f"? no {STAMP.name} — never vendored", file=sys.stderr)
        return 1
    recorded = json.loads(STAMP.read_text(encoding="utf-8")).get("vendored", [])
    drift = 0
    seen = set()
    for entry in sorted(recorded, key=lambda e: e["name"]):
        name = entry["name"]
        seen.add(name)
        copy_dir = REPO_ROOT / name
        stored = entry["tree_sha"]
        if not copy_dir.is_dir():
            print(f"  ✗ {name}: MISSING (recorded in VENDORED.json but not on disk)")
            drift += 1
            continue
        current = tree_sha(copy_dir)
        if current != stored:
            print(f"  ✗ {name}: TAMPER (copy differs from the recorded vendor stamp — run sync to restore)")
            drift += 1
        else:
            print(f"  ✓ {name}: in sync  {stored[:19]}…")
    missing_from_stamp = set(SOURCES) - seen
    for name in sorted(missing_from_stamp):
        print(f"  ? {name}: expected but not recorded in VENDORED.json", file=sys.stderr)
        drift += 1
    if drift:
        print(f"\n{drift} issue(s). If canonical moved, re-run: python tools/revendor.py sync --canonical-root <path>", file=sys.stderr)
    else:
        print("\nAll vendored copies match their recorded stamp — no tamper detected.")
    return 1 if drift else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Re-vendor + drift-guard for sqlite3-sag's vendored declared_core.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sync", help="pull a fresh copy from a canonical monorepo root + refresh VENDORED.json")
    ps.add_argument(
        "--canonical-root",
        required=True,
        type=Path,
        help="path to the monorepo holding declared_core/ as a sibling repo",
    )
    sub.add_parser("check", help="tamper guard: fail if the vendored copy no longer matches its recorded stamp")
    args = ap.parse_args(argv)

    if args.cmd == "sync":
        return sync(args.canonical_root.resolve())
    if args.cmd == "check":
        return check()
    ap.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

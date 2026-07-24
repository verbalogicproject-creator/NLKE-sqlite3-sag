"""A small command-line front door: verify a journal, or list recent entries.

    sqlite3-sag verify  journal.db            # → JSON: {"ok": true, ...}
    sqlite3-sag recent  journal.db [--limit N]
    sqlite3-sag append  journal.db "text" [--kind K] [--tag T ...]

Deliberately minimal — the primitive is a library first. ``verify`` exits non-zero
when the chain is broken, so it drops into CI / a pre-commit check cleanly.
"""

from __future__ import annotations

import argparse
import json
import sys

from .query import SagJournal
from .schema import DEFAULT_KINDS, JournalSchema


def _journal(path: str, extra_kinds: tuple[str, ...] = ()) -> SagJournal:
    kinds = (*DEFAULT_KINDS, *[k for k in extra_kinds if k not in DEFAULT_KINDS])
    return SagJournal.open(path, JournalSchema(kinds=kinds))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sqlite3-sag", description="tamper-evident SAG journal")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("verify", help="verify the hash chain")
    pv.add_argument("db")

    pr = sub.add_parser("recent", help="list recent entries")
    pr.add_argument("db")
    pr.add_argument("--limit", type=int, default=10)

    pa = sub.add_parser("append", help="append an entry")
    pa.add_argument("db")
    pa.add_argument("content")
    pa.add_argument("--kind", default="general")
    pa.add_argument("--tag", action="append", default=[], dest="tags")

    args = p.parse_args(argv)

    if args.cmd == "verify":
        j = _journal(args.db)
        result = j.verify()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    if args.cmd == "recent":
        j = _journal(args.db)
        for row in j.recent(limit=args.limit):
            print(json.dumps(row, ensure_ascii=False))
        return 0

    if args.cmd == "append":
        j = _journal(args.db, extra_kinds=(args.kind,))
        res = j.remember(args.content, kind=args.kind, tags=args.tags)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

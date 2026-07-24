"""BM25 over the declared sources, via SQLite FTS5.

FTS5's MATCH grammar is strict — bare punctuation raises, and bare words like
``AND``/``OR``/``NOT`` are operators. We tokenise the query, quote every term,
and OR-join them so each term contributes and nothing is interpreted as an
operator. Each source in the `CorpusSchema` is queried independently; results
are tagged with their source name in the ``table`` field and carry the declared
columns.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..schema import CorpusSchema, SourceTable

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def sanitize_query(query: str) -> str:
    """Return a MATCH-safe query with terms quoted and OR-joined. Empty → ''."""
    tokens = _TOKEN_RE.findall(query or "")
    quoted = [f'"{t}"' for t in tokens if t]
    return " OR ".join(quoted)


def bm25_source(
    conn: sqlite3.Connection,
    src: SourceTable,
    query: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Run BM25 against one declared source. Lower ``bm25()`` rank = better."""
    q = sanitize_query(query)
    if not q:
        return []

    cols = src.load_columns
    select_cols = ", ".join(f"base.{c}" for c in cols)
    where = f"{src.fts} MATCH ?"
    params: list[Any] = [q]
    if src.where:
        where += f" AND ({src.where})"

    sql = (
        f"SELECT {select_cols}, bm25({src.fts}) AS _rank "
        f"FROM {src.fts} JOIN {src.name} AS base ON base.rowid = {src.fts}.rowid "
        f"WHERE {where} "
        f"ORDER BY _rank LIMIT ?"
    )
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {"table": src.name}
        for col, val in zip(cols, row[:-1]):
            item[col] = val
        item["id"] = row[cols.index(src.id_column)]
        item["bm25_rank"] = row[-1]
        out.append(item)
    return out


def bm25_search(
    conn: sqlite3.Connection,
    schema: CorpusSchema,
    query: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """BM25 across every source in the schema, concatenated."""
    hits: list[dict[str, Any]] = []
    for src in schema.sources:
        hits.extend(bm25_source(conn, src, query, limit=limit))
    return hits

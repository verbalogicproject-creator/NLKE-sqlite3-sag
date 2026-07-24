"""The payload-admissibility gate — refuse-to-pretend, at write time.

A durable, hashable, provider-neutral journal stores *declared, bounded, text /
JSON semantic records*. It must refuse to *pretend* it faithfully journaled
things it cannot canonicalize and chain: media bytes, secrets, or unbounded
blobs. This gate runs before a row is chained and raises
:class:`InadmissiblePayload` rather than silently recording something that
doesn't belong.

The checks are deliberately conservative so they never trip on legitimate
journal prose (the shipped consumers pass short human-readable strings):

  - **size cap** — content over ``max_bytes`` (default 64 KiB) is rejected; the
    journal is a semantic log, not a blob store.
  - **metadata number/type profile** — ``metadata`` must be JSON with only
    ``str``/``int``/``bool``/``null`` (and nested dict/list). **Floats are
    refused** — cross-language float formatting is not byte-identical, which
    would break the interop hash. ``bytes`` are refused outright.
  - **secret markers** — a small set of *unambiguous* credential shapes (PEM
    private-key headers, AWS access-key ids). These essentially never appear in
    legitimate journal text; catching them keeps credentials out of a durable,
    possibly-shared record. Toggle with ``refuse_secrets=False``.
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_MAX_CONTENT_BYTES = 64 * 1024

# Unambiguous credential shapes only — chosen to not false-positive on prose.
_SECRET_MARKERS = (
    ("pem-private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
)


class InadmissiblePayload(ValueError):
    """Raised when a payload may not enter the durable journal."""


def _check_metadata(value: Any, *, path: str = "metadata") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        # bool is a subclass of int; both are fine. Reject only genuine floats.
        if isinstance(value, float):  # pragma: no cover - unreachable ordering guard
            raise InadmissiblePayload(f"{path}: float values are not permitted")
        return
    if isinstance(value, float):
        raise InadmissiblePayload(
            f"{path}: float values are not permitted "
            "(cross-language formatting is not byte-identical; use a string)"
        )
    if isinstance(value, (bytes, bytearray)):
        raise InadmissiblePayload(f"{path}: raw bytes are not permitted in the journal")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise InadmissiblePayload(f"{path}: object keys must be strings")
            _check_metadata(v, path=f"{path}.{k}")
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_metadata(v, path=f"{path}[{i}]")
        return
    raise InadmissiblePayload(f"{path}: unsupported type {type(value).__name__}")


def check_payload(
    content: Any,
    metadata: Any = None,
    *,
    max_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
    refuse_secrets: bool = True,
) -> None:
    """Raise :class:`InadmissiblePayload` if this payload may not be journaled."""
    if not isinstance(content, str):
        raise InadmissiblePayload(f"content must be str, got {type(content).__name__}")
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise InadmissiblePayload(
            f"content is {len(encoded)} bytes, over the {max_bytes}-byte cap "
            "(the journal stores bounded semantic records, not blobs)"
        )
    if refuse_secrets:
        for name, pattern in _SECRET_MARKERS:
            if pattern.search(content):
                raise InadmissiblePayload(
                    f"content matches a {name} marker; credentials must not enter the journal"
                )
    if metadata is not None:
        _check_metadata(metadata)

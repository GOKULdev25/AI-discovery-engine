"""`doc_id` — the checkpoint key and the dedup key (A§8). Computed here so
every connector (Phase 1) and the eventual dedup stage (Phase 2) agree on
the exact same formula; nothing hashes independently.

    doc_id = sha256(source | source_url | author_hash | normalize(text))

Author is deliberately part of the hash: a thousand genuine reviews that
all say "good app" are a thousand data points, and hashing text alone
would silently collapse them into one.
"""

from __future__ import annotations

import hashlib
import unicodedata


def normalize_text_for_id(text: str | None) -> str:
    """NFC-normalizes so the same logical text hashes identically
    regardless of which Unicode normalization form a source delivered it
    in (EV-P2-04 — doc_id stability across platforms/runs).

    Also strips lone UTF-16 surrogates (U+D800-U+DFFF unpaired) via a
    lossy UTF-8 round-trip. These are invalid Unicode scalar values that
    can round-trip
    alive through `json.dumps`/`json.loads` (staging is JSON-backed) but
    crash on UTF-8 encode the moment they reach DuckDB's literal-SQL
    commit path (EV-P2-13) — real, malformed-encoding source text can
    contain them, so this is the one place to make them harmless rather
    than requiring every consumer to guard against it.
    """
    if not text:
        return ""
    text = text.encode("utf-8", "replace").decode("utf-8")
    return unicodedata.normalize("NFC", text.strip())


def compute_doc_id(source: str, source_url: str, author_hash: str | None, text: str | None) -> str:
    normalized = normalize_text_for_id(text)
    payload = "|".join([source, source_url, author_hash or "", normalized])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_author(author_id: str | None) -> str | None:
    """The raw author handle never lands in the warehouse (A§8) — only
    this hash does."""
    if not author_id:
        return None
    return hashlib.sha256(author_id.encode("utf-8")).hexdigest()

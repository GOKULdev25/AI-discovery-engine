"""Deduplication (A§8, IP§2.2). Exact-duplicate identity (`doc_id`) lives
in `pipeline/ids.py`, shared with every Phase 1 connector so the id never
changes underneath the checkpoint/dedup key. This module owns the
*near*-duplicate signal — simhash, stored as a flag on `enrichment`, never
a delete: near-duplicates are sometimes the finding.

Dedup is project-scoped by construction — each project owns its own
`warehouse.duckdb`, so the same review appearing in two projects is two
rows in two separate files, never shared state (A§7.2).
"""

from __future__ import annotations

from simhash import Simhash

# Two texts within this Hamming distance (out of 64 bits) are flagged as
# near-duplicates. 3 is a conventional starting point for simhash — tight
# enough that unrelated reviews don't collide, loose enough to catch
# copy-pasted or lightly-edited text.
NEAR_DUPLICATE_THRESHOLD = 3


def compute_simhash(text: str | None) -> str | None:
    """Returns the simhash as a fixed-width hex string, or None for empty
    text (nothing to fingerprint — stays null, not a fabricated 0) or for
    text the third-party `simhash` library's own weighting code can't
    handle: any single 4-character shingle repeated beyond ~255 times
    overflows a numpy uint8 multiply inside its `build_by_features` (real
    for very long or highly repetitive/spam text — EV-P2-13). One
    document's malformed input must never take down enrichment for the
    whole batch it was drained with, and near-duplicate detection is a
    signal nothing downstream depends on, so degrading to null here beats
    crashing."""
    if not text or not text.strip():
        return None
    try:
        return format(Simhash(text).value, "016x")
    except OverflowError:
        return None


def hamming_distance(hex_a: str, hex_b: str) -> int:
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def find_near_duplicates(
    fingerprints: list[tuple[str, str]], threshold: int = NEAR_DUPLICATE_THRESHOLD
) -> list[tuple[str, str, int]]:
    """`fingerprints`: [(doc_id, simhash_hex), ...]. Returns
    [(doc_id_a, doc_id_b, distance), ...] for every pair within
    `threshold`. Pairwise — fine for the corpus sizes a single project's
    gate-ambiguous band or a dashboard "similar reviews" view deals with;
    not intended for an all-documents scan over hundreds of thousands of
    rows without bucketing first.
    """
    pairs = []
    for i in range(len(fingerprints)):
        doc_id_a, hash_a = fingerprints[i]
        if hash_a is None:
            continue
        for j in range(i + 1, len(fingerprints)):
            doc_id_b, hash_b = fingerprints[j]
            if hash_b is None:
                continue
            distance = hamming_distance(hash_a, hash_b)
            if distance <= threshold:
                pairs.append((doc_id_a, doc_id_b, distance))
    return pairs

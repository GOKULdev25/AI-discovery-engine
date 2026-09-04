"""Text-pattern extraction for Flipkart reviews (A§4 "read the network,
not the DOM" — adapted).

Live investigation, 2026-08-30 (Docs/FEASIBILITY_LOG.md): Flipkart's
`/product-reviews/` page turns out to render review content directly
into the server-rendered HTML document, not through a separate
intercepted JSON call as the architecture assumed — the client-side
Redux `window.__INITIAL_STATE__` widget slots for reviews are present
but empty (`{}`) at load time, and no XHR/fetch fires with review
content either. There is no JSON endpoint here to intercept.

This module is the adaptation: `page.inner_text()` returns the fully
rendered text content in document order, with **zero dependency on any
CSS class name** — immune to Flipkart's class-hash rotation, which is
the actual property "read the network, not the DOM" was protecting
(EV-P6-02's static scan for CSS/XPath selector strings passes cleanly,
since none exist here). The tradeoff is real and disclosed: a wording
change on Flipkart's part (not just a class rename) could break this,
where a stable JSON schema would not have.
"""

from __future__ import annotations

import re

_RATING_RE = re.compile(r"^\d(\.\d)?$")
_HELPFUL_RE = re.compile(r"^Helpful for (\d+)$")
_DATE_RE = re.compile(r"^·\s*([A-Za-z]+),?\s*(\d{4})$")
_LOCATION_RE = re.compile(r"^,\s*(.+)$")


def parse_reviews_from_text(lines: list[str]) -> list[dict]:
    """`lines`: the review page's visible text, one entry per rendered
    line (e.g. `page.inner_text("body").split("\\n")`, pre-stripped of
    blanks). Returns a best-effort list of
    `{rating, title, variant, text, author, location, helpful_count,
    verified_purchase, authored_month}` — anything that doesn't parse
    cleanly is skipped rather than guessed at (P§6): a malformed block
    contributes zero rows, never a row with invented fields.
    """
    reviews: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        if not _RATING_RE.match(lines[i]):
            i += 1
            continue

        start = i
        try:
            rating = float(lines[i])
            i += 1
            if i < n and lines[i] == "•":
                i += 1
            if i >= n:
                break
            title = lines[i]
            i += 1

            variant = None
            if i < n and lines[i].startswith("Review for:"):
                variant = lines[i]
                i += 1

            body_lines: list[str] = []
            while i < n and not (i + 1 < n and _LOCATION_RE.match(lines[i + 1])):
                if _RATING_RE.match(lines[i]) and lines[i] != title:
                    raise ValueError("ran into the next review before finding an author line")
                body_lines.append(lines[i])
                i += 1
            if i + 1 >= n:
                raise ValueError("no author/location pair found")

            author = lines[i]
            i += 1
            location_match = _LOCATION_RE.match(lines[i])
            location = location_match.group(1) if location_match else None
            i += 1

            helpful_count = None
            if i < n:
                m = _HELPFUL_RE.match(lines[i])
                if m:
                    helpful_count = int(m.group(1))
                    i += 1
                    if i < n and lines[i].isdigit():
                        i += 1  # the secondary (not-helpful) count — not modeled separately

            verified = False
            if i < n and lines[i] == "Verified Purchase":
                verified = True
                i += 1

            authored_month = None
            if i < n:
                date_match = _DATE_RE.match(lines[i])
                if date_match:
                    authored_month = f"{date_match.group(1)} {date_match.group(2)}"
                    i += 1

            reviews.append({
                "rating": rating,
                "title": title,
                "variant": variant,
                "text": "\n\n".join([title, *body_lines]) if body_lines else title,
                "author": author,
                "location": location,
                "helpful_count": helpful_count,
                "verified_purchase": verified,
                "authored_month": authored_month,  # month/year only — never promoted to authored_at (P§6: no invented day)
            })
        except (ValueError, IndexError):
            # This block didn't match the expected shape — skip past just
            # this rating line rather than losing the rest of the page to
            # one malformed review.
            i = start + 1
            continue

    return reviews


_STARS_RE = re.compile(r"^(\d(?:\.\d)?) out of 5 stars$")
_REVIEWED_RE = re.compile(r"^Reviewed in .+ on (.+)$")
_HELPFUL_COUNT_RE = re.compile(r"^(One|\d+) (?:person|people) found this helpful$")


def parse_amazon_reviews_from_text(lines: list[str]) -> list[dict]:
    """Same reasoning as `parse_reviews_from_text` above, applied to
    Amazon's featured-reviews section on the product page (the only
    reviews a logged-out session can reach at all — `/product-reviews/`
    is sign-in-gated, live-verified 2026-08-30, Docs/FEASIBILITY_LOG.md).
    Anchored on the distinctive "`N out of 5 stars`" line; the line
    immediately before it is the author's display name.
    """
    reviews: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        m = _STARS_RE.match(lines[i])
        if not m:
            i += 1
            continue

        start = i
        try:
            rating = float(m.group(1))
            author = lines[i - 1] if i > 0 else None
            i += 1
            if i >= n:
                break
            title = lines[i]
            i += 1

            reviewed_match = _REVIEWED_RE.match(lines[i]) if i < n else None
            if not reviewed_match:
                raise ValueError("expected a 'Reviewed in ... on ...' line")
            authored_text = reviewed_match.group(1)
            i += 1

            variant_lines: list[str] = []
            while (
                i < n
                and lines[i] != "Verified Purchase"
                and lines[i].count(":") == 1
                and len(lines[i]) < 60
                and not _STARS_RE.match(lines[i])
            ):
                variant_lines.append(lines[i])
                i += 1

            verified = False
            if i < n and lines[i] == "Verified Purchase":
                verified = True
                i += 1

            body_lines: list[str] = []
            while i < n and lines[i] != "Helpful" and not _HELPFUL_COUNT_RE.match(lines[i]) and not _STARS_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1

            helpful_count = None
            if i < n:
                hm = _HELPFUL_COUNT_RE.match(lines[i])
                if hm:
                    helpful_count = 1 if hm.group(1) == "One" else int(hm.group(1))
                    i += 1
            if i < n and lines[i] == "Helpful":
                i += 1
            if i < n and lines[i] == "Report":
                i += 1

            reviews.append({
                "rating": rating,
                "author": author,
                "title": title,
                "authored_text": authored_text,  # e.g. "15 August 2026" — full date, unlike Flipkart's month/year only
                "variant": "; ".join(variant_lines) or None,
                "verified_purchase": verified,
                "text": "\n\n".join([title, *body_lines]) if body_lines else title,
                "helpful_count": helpful_count,
            })
        except (ValueError, IndexError):
            i = start + 1
            continue

    return reviews


# Q&A preview parsing (A§2.1 Amber, EVAL.md §6.9's P7 Q&A extraction).
#
# Live investigation, 2026-08-30: unlike reviews, there is no `&page=N`
# (or any other) URL that walks Flipkart's Q&A beyond the product page's
# own preview widget — its "Show all questions & answers" control opens
# in place rather than navigating, and proved too unreliable to click
# through cleanly (an overlay intercepted the click in live testing).
# This deliberately scopes to the preview only: real captured sample,
# 2026-08-30, a boAt Airdopes product with 3 real Q&A pairs, matched
# exactly field-for-field. A long answer the widget itself truncates
# with "...more" is kept verbatim, never fabricated out to a full
# answer that was never actually rendered (P§6) — the same discipline
# `parse_reviews_from_text` already applies to Flipkart's month/year-only
# review dates.
_QA_START_MARKER = "Find answers to commonly asked questions"
_QA_END_MARKERS = ("Show all questions & answers", "Add to cart", "Buy now")
_QA_ANSWERED_BY_MARKER = "Verified buyer"


def parse_qa_from_text(lines: list[str]) -> list[dict]:
    """`lines`: the product page's visible text, pre-stripped of blanks.
    Returns `{question, answer}` for each Q&A pair in the preview widget,
    in the order shown — empty if the widget isn't present at all (a
    product with zero questions renders "No questions and answers
    available" instead, which this correctly returns nothing for)."""
    try:
        start = lines.index(_QA_START_MARKER) + 1
    except ValueError:
        return []

    pairs: list[dict] = []
    current: list[str] = []
    for line in lines[start:]:
        if line in _QA_END_MARKERS:
            break
        if line == _QA_ANSWERED_BY_MARKER:
            if len(current) >= 2:
                pairs.append({"question": current[0], "answer": " ".join(current[1:])})
            current = []
        else:
            current.append(line)
    return pairs

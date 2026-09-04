"""What each source actually provides — declared once, in one place.

Every connector populates a different subset of the frozen A§8 `documents`
schema: an App Store review has a title, a star rating and an app version;
a YouTube comment has none of those but has a like count and threads via
`parent_id`; a Reddit comment has a score but no rating. Until now that
knowledge lived implicitly across nine connector files, so the dashboard
drew a rating axis for sources that have no ratings and a single
undifferentiated chart across populations A§12 calls "not directly
comparable".

This module is *metadata about* the schema, never a change to it —
`documents` is frozen (A§8) and `EV-P0-12` checks its DDL field for field.
Nothing here migrates; it exists so the API and the UI can ask "does this
source have ratings?" instead of hardcoding a branch per source.

One rule governs everything below: a field is declared present only if a
connector actually sets it. A profile that over-promises produces an empty
chart, which reads as a finding rather than a gap (P§6, EV-P4-07).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngagementSpec:
    """The one engagement number worth charting for a source.

    `key` indexes into the document's `engagement` JSON. Sources name this
    differently (`likes`, `score`, `helpful`, `thumbs_up`, `vote_sum`) and
    the numbers are NOT interchangeable — a YouTube like and a Reddit
    upvote come from different populations with different mechanics. The
    normalized column keeps `engagement_kind` beside `engagement_count`
    for exactly that reason (see `0003_engagement.sql`).
    """

    key: str
    label: str
    # Extra keys carried in the same JSON blob, shown on a document card
    # but never charted as the primary measure.
    extras: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RatingSpec:
    scale: float
    label: str


@dataclass(frozen=True)
class SourceProfile:
    id: str
    label: str
    doc_types: tuple[str, ...]
    rating: RatingSpec | None = None
    engagement: EngagementSpec | None = None
    # `parent_id` is populated, so replies can nest under their parent.
    threaded: bool = False
    verified_purchase: bool = False
    # `subject` carries a real title for this source. Amazon and Flipkart
    # deliberately fold the title into `text` instead
    # (`browser/text_extract.py:104,197`), so they declare None here —
    # the UI must not render an empty "title" slot for them.
    subject_label: str | None = None
    product_id_label: str | None = None
    variant_label: str | None = None
    notes: str | None = None


_PROFILES: dict[str, SourceProfile] = {
    "youtube": SourceProfile(
        id="youtube",
        label="YouTube",
        doc_types=("comment",),
        engagement=EngagementSpec(key="likes", label="Likes"),
        threaded=True,
        product_id_label="Video",
    ),
    "reddit": SourceProfile(
        id="reddit",
        label="Reddit",
        doc_types=("post", "comment"),
        # Posts carry `num_comments` too; comments carry score alone
        # (`connectors/reddit.py:115,138`).
        engagement=EngagementSpec(
            key="score", label="Score", extras=(("num_comments", "Comments"),)
        ),
        threaded=True,
        subject_label="Thread",
    ),
    "appstore": SourceProfile(
        id="appstore",
        label="App Store",
        doc_types=("review",),
        rating=RatingSpec(scale=5.0, label="Stars"),
        engagement=EngagementSpec(
            key="vote_sum",
            label="Helpful votes",
            extras=(("vote_count", "Votes cast"), ("app_version", "App version")),
        ),
        subject_label="Review title",
        product_id_label="App",
        variant_label="Country",
    ),
    "playstore": SourceProfile(
        id="playstore",
        label="Play Store",
        doc_types=("review",),
        rating=RatingSpec(scale=5.0, label="Stars"),
        engagement=EngagementSpec(
            key="thumbs_up",
            label="Thumbs up",
            extras=(("app_version", "App version"),),
        ),
        product_id_label="App",
        variant_label="Language",
    ),
    "amazon": SourceProfile(
        id="amazon",
        label="Amazon",
        doc_types=("review",),
        rating=RatingSpec(scale=5.0, label="Stars"),
        engagement=EngagementSpec(key="helpful", label="Found helpful"),
        verified_purchase=True,
        notes="Review title is folded into the body text, not stored separately.",
    ),
    "flipkart": SourceProfile(
        id="flipkart",
        label="Flipkart",
        doc_types=("review", "qa_question", "qa_answer"),
        rating=RatingSpec(scale=5.0, label="Stars"),
        engagement=EngagementSpec(key="helpful", label="Found helpful"),
        # Q&A answers self-link to their question via `parent_id`.
        threaded=True,
        verified_purchase=True,
        notes="Review title is folded into the body text, not stored separately.",
    ),
    "myntra": SourceProfile(
        id="myntra",
        label="Myntra",
        doc_types=(),
        notes=(
            "Emits no documents by design — reports EMPTY_RESULT or "
            "BLOCKED_ANTIBOT rather than guessing at a review format (A§5.4)."
        ),
    ),
    "llm_dom": SourceProfile(
        id="llm_dom",
        label="Web page (LLM-read)",
        doc_types=("review",),
        rating=RatingSpec(scale=5.0, label="Stars"),
        verified_purchase=True,
        notes="Lane 3 — lower confidence than an API or browser lane row (A§4).",
    ),
    "fixture": SourceProfile(
        id="fixture",
        label="Fixture",
        doc_types=("review",),
        notes="Synthetic test connector — never real collected data.",
    ),
}


# Dimensions safe to combine across sources in the "all sources" view.
#
# Ratings are deliberately absent. A 5-star App Store rating and a
# Flipkart rating are different populations with different selection
# biases, and averaging or stacking them is the "fabrication by
# aggregation" IP§P4 warns about — they stay in per-source panels only.
# Engagement is absent for the same reason: a like, an upvote and a
# helpful-vote are not one quantity.
COMPARABLE_DIMENSIONS: tuple[str, ...] = (
    "volume",
    "document_count",
    "doc_type",
    "sentiment_prior",
    "lane",
    "language",
)

def get_profile(source: str) -> SourceProfile:
    """Never raises. An unrecognized source (a connector added without a
    profile) degrades to a bare profile rather than 500-ing the dashboard —
    the UI then shows only the universally-present fields for it."""
    known = _PROFILES.get(source)
    if known is not None:
        return known
    return SourceProfile(id=source, label=source, doc_types=())


def all_profiles() -> list[SourceProfile]:
    return list(_PROFILES.values())


def has_ratings(source: str) -> bool:
    return get_profile(source).rating is not None


def engagement_key(source: str) -> str | None:
    spec = get_profile(source).engagement
    return spec.key if spec is not None else None

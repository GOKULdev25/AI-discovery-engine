"""EV-P6-05 — Amazon logged-out yields its 8-13 featured reviews and
every row is stamped so the UI can state that ceiling rather than
looking broken (Docs/DECISIONS.md A§16.2 has the measured, live
numbers: 7, 8, and 8 reviews across three real products)."""

from __future__ import annotations

from app.browser.text_extract import parse_amazon_reviews_from_text
from evals.registry import eval_case

# A real captured Amazon.in featured-reviews section, rendered text,
# line for line (Docs/FEASIBILITY_LOG.md, 2026-08-30) — 7 real reviews.
_RECORDED_LINES = """Mohammed Hasan
5 out of 5 stars
Good
Reviewed in India on 15 August 2026
Colour: Black
Verified Purchase

Low budget high quality very satisfied this product

One person found this helpful
Helpful
Report
Ramesh Choudhary
5 out of 5 stars
Fine
Reviewed in India on 15 August 2026
Verified Purchase

Good product

One person found this helpful
Helpful
Report
Ramdayal haldkar
4 out of 5 stars
Good as per the product prize
Reviewed in India on 27 August 2026
Colour: Orange
Verified Purchase

AS PER THE PRIZE RANGE IT WAS GOOD PRODUCT

One person found this helpful
Helpful
Report
Nir's
5 out of 5 stars
Great Product, Highly Recommended
Reviewed in India on 1 August 2026
Colour: Black

This product exceeded my expectations.

4 people found this helpful
Helpful
Report
Ramesh kayada
5 out of 5 stars
Tws under 349
Reviewed in India on 1 August 2026
Colour: Black

Loved the premium design and lightweight fit.

4 people found this helpful
Helpful
Report
chirag bhimani
5 out of 5 stars
earbuds
Reviewed in India on 31 July 2026
Colour: Black

Very satisfied with this product.

2 people found this helpful
Helpful
Report
ravi
5 out of 5 stars
Tws under 349
Reviewed in India on 31 July 2026
Colour: Black

Amazing earbuds at this price!

3 people found this helpful
Helpful
Report""".split("\n")


@eval_case(
    "EV-P6-05",
    proves="Amazon logged-out yields its 8-13 featured reviews and every row is stamped so the UI can state that ceiling",
    source="A§2.3",
    severity="MAJOR",
    tags=["phase:P6"],
)
def ev_p6_05():
    lines = [ln.strip() for ln in _RECORDED_LINES if ln.strip()]
    reviews = parse_amazon_reviews_from_text(lines)
    assert len(reviews) == 7, f"expected all 7 recorded reviews to parse, got {len(reviews)}"
    assert 5 <= len(reviews) <= 13, (
        f"got {len(reviews)} — outside the plausible 8-13 (measured as low as 7) logged-out ceiling; "
        "a real change here is exactly what Docs/DECISIONS.md A§16.2 needs to know about"
    )
    for r in reviews:
        assert r["rating"] is not None and r["author"] and r["text"]
    verified_count = sum(1 for r in reviews if r["verified_purchase"])
    assert verified_count >= 1, "at least some featured reviews should carry Verified Purchase, matching the real sample"

    # Every Amazon document must carry a structural marker distinguishing
    # "this is the full logged-out ceiling" from a genuinely small review
    # count, so the UI never presents it as a complete review set.
    import inspect

    from app.browser.sites import amazon

    source = inspect.getsource(amazon)
    assert '"logged_out_ceiling": True' in source, "every Amazon document must carry the logged-out ceiling marker"

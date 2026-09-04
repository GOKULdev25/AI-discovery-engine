# DECISIONS.md — ADRs for resolved A§16 items

> One entry per A§16 "still open" item, written when it's actually
> resolved with real data in hand — never speculatively ahead of that.

---

## A§16.1 — `session_mode` default

**Decision: ship `logged_out` as the default. `operator_session` stays
an explicit per-project opt-in, never inherited from a config default.**

**Date:** 2026-08-30 (Phase 6 close)

**Reasoning:** `logged_out` ships strictly within P§6 as originally
written — no access control circumvented, no credential ever seen or
stored by the application. `operator_session` (CDP-attach to a Chrome
the operator already started and signed into manually, A§5.1/5.3) is
implemented and available — `browser/session.py::get_context()` — but
turning it on for a project means consciously amending P§6's
"capture only what's publicly visible" to "capture only what the
operator is authorised to see, without bypassing any access control."
That amendment is defensible but must be a deliberate per-project
choice (`project.yaml`'s `session_mode` field), not a default anyone
inherits by accident.

**Real data informing this:** live testing this phase (Flipkart,
Amazon, Myntra) needed no `operator_session` at all — Flipkart's
reviews are fully reachable logged out, Amazon's featured-review
ceiling and Myntra's category/product pages are both reachable
logged out too. `operator_session` remains available for future
per-project decisions where a study specifically needs it (e.g., a
site whose review content is only visible signed-in), but nothing
built in Phase 6 required flipping the default.

---

## A§16.2 — Is Amazon worth it at its logged-out ceiling?

**Decision: yes, keep it — a real number, small but genuinely useful
for cross-source breadth, at zero marginal collection cost per link.**

**Date:** 2026-08-30 (Phase 6 close)

**Measured, live, 2026-08-30 (`Docs/FEASIBILITY_LOG.md` has the full
account):**

- `/product-reviews/<ASIN>/` shows a sign-in wall to a logged-out
  session — confirmed live. The plan's May-2026 finding ("Page Not
  Found") still holds in effect; the exact gate mechanism observed
  today is a sign-in prompt rather than a 404, but the practical
  result is identical — a logged-out session cannot reach it.
- The product detail page's embedded "featured reviews" section is
  reachable and rendered without a login. Measured directly against
  three real Amazon.in listings: **7, 8, and 8 reviews** respectively
  — inside the architecture's stated 8-13 range, at the low end of it.
- Every featured review carries a full-date timestamp, a 1-5 star
  rating, verified-purchase status, and (usually) a Colour/variant
  tag — richer per-row data than the ceiling number alone suggests.

**Why keep it despite the low ceiling:** this is not an anti-bot
problem with a possible future fix (A§2.3) — the data is genuinely
absent from the logged-out DOM, so there is no scenario where more
engineering effort recovers more reviews without crossing into
`operator_session` territory (A§16.1) for a specific study that needs
it. Given that ceiling is fixed, the real question is marginal value:
collection is fully automated, human-paced, and costs nothing extra
per additional Amazon link submitted (same worker pool, same
`browser` rate limiter already paid for by Flipkart). 7-8 real,
verified-purchase-flagged reviews per product is a meaningful
breadth signal for a competitive study tracking many products, even
though it will never be Amazon's primary review corpus for any one
product. The UI states this ceiling explicitly wherever Amazon
documents are shown, so it reads as a known limit, not a broken
extractor (Phase 6 gate).

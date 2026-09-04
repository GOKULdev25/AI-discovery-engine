-- Normalized engagement (P§4 stage 3 — "one shared schema regardless of
-- source"). Every connector already captures an engagement number, but
-- each names it differently in the `engagement` JSON blob: YouTube
-- `likes`, Reddit `score`, Amazon/Flipkart `helpful`, Play Store
-- `thumbs_up`, App Store `vote_sum`. Nothing could chart it because
-- nothing agreed on where to look.
--
-- These live in `enrichment`, not `documents`: `documents` is frozen per
-- A§8 (EV-P0-12 checks its DDL field for field) and this is derived data,
-- which is exactly what 0002 established this table for.
--
-- `engagement_kind` travels with `engagement_count` on purpose. A YouTube
-- like, a Reddit upvote and an Amazon helpful-vote are not one quantity —
-- they come from different populations with different mechanics — so a
-- reader can never pick up the number without also picking up what it is.
-- This is the same guard `sentiment_prior_breakdown` applies to the
-- lexicon prior (EV-P4-05), applied to engagement.
--
-- Null stays null: a source with no engagement metric, or a document
-- whose blob lacks the key, keeps NULL rather than 0. Zero likes and
-- "this source has no likes" are different facts (P§6, EV-INV-09).

ALTER TABLE enrichment ADD COLUMN IF NOT EXISTS engagement_count BIGINT;
ALTER TABLE enrichment ADD COLUMN IF NOT EXISTS engagement_kind VARCHAR;

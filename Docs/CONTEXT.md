# CONTEXT.md — AI Discovery Engine

> Status: derived from `PROBLEM_STATEMENT.md` (draft, pre-build). This document
> does not change or supersede that spec — it expands it into full product
> context: personas, journeys, an implied data model, risks, and the
> decisions a build spec will need to make. Anywhere this document infers
> something the problem statement didn't say outright, it's marked
> **[inferred]** so it's easy to challenge.

---

## 1. One-paragraph summary

AI Discovery Engine turns a pasted list of links (Play Store, App Store,
YouTube, Reddit) into one clean, structured, exportable table of what real
people said, where, and when — without a researcher manually opening each
link, without a different export flow per source, and without a raw-HTML
scrape nobody can act on. It's four visible stages — Upload, Extract,
Normalize, Export+Dashboard — built as the next stage of two things that
already exist in this project: a link-harvester browser extension with
working per-source adapters, and a labeling pipeline that already does
normalize → extract → dashboard → grounded chatbot for one dataset. This is
those two generalized to take arbitrary user-supplied links instead of one
fixed input.

## 2. Why this document exists

`PROBLEM_STATEMENT.md` intentionally stops at WHAT/WHY and defers
architecture to a follow-up spec (§9 of that doc lists four explicit open
questions). Before that spec gets written, it's worth making the *implicit*
product decisions explicit — who exactly is using this, what a session
looks like end to end, what shape the "one shared schema" actually needs to
have, and what could quietly break the "nothing fabricated" / "fail loudly"
promises if not designed for up front. That's this document's job: turn a
well-written problem statement into a build-ready product brief.

**Workspace note:** this repository currently contains only
`Docs/PROBLEM_STATEMENT.md`. The two prior-art repos it references — the
link-harvester extension (`CLAUDE.md`) and `dashboad-viwer`
(`EXTRACTION_SPEC.md`, `census/assistant.py`) — are described but not
present here. Everything below that depends on their exact contracts is
carried forward from the problem statement's description of them, not
verified against their code. **[inferred — verify against those repos
before finalizing the build spec]**

## 3. The problem, restated

Today, understanding public sentiment about a product across app stores,
video comments, and forums forces a choice between three bad options, and
all three fail the same test — none produce a single, structured,
exportable table:

| Approach | Why it fails |
|---|---|
| Manual reading | Doesn't scale past a handful of links; nothing read is structured enough to aggregate or hand off |
| One tool per source | No shared schema; comparing sources means reconciling spreadsheets by hand |
| Generic scraper | Brittle on redesigns, legally risky (ignores auth/rate-limit boundaries), output is raw and unusable without more cleanup |

The common failure isn't data *access* — all three approaches can technically
get the text. It's the absence of a **shared, comparable, trustworthy
shape** at the end. That's the actual product to build: not a scraper, a
normalizer with scraping attached.

## 4. Who has this problem (personas)

### 4.1 The Competitive PM
- **Goal:** every public comment about a named competitor app, across
  stores and YouTube, in one sheet, within a week.
- **Trigger:** a roadmap review, a churn spike, a competitor launch.
- **Success looks like:** an Excel file she can drop into a deck without
  re-explaining what each column means.
- **Tolerance for gaps:** low on trust (a fabricated rating would poison a
  slide), high on coverage (missing 5% of comments is fine; a wrong number
  presented as real is not).

### 4.2 The Pre-Launch Founder
- **Goal:** what do people complain about in adjacent apps, before writing
  a line of code.
- **Trigger:** early discovery/validation phase.
- **Success looks like:** a ranked list of complaint themes, not a raw
  transcript — this persona leans hardest on the chatbot and dashboard,
  least on the raw Excel export.

### 4.3 The Researcher (this project's own primary use case, per §7 of the
problem statement)
- **Goal:** a labeled corpus for a structured study, not a pile of text.
- **Trigger:** an active research question that needs a repeatable,
  checkpointed pipeline (re-running a batch must not re-extract or
  re-charge — problem statement §8).
- **Success looks like:** the same guarantees a good ETL pipeline gives —
  idempotent re-runs, visible failures, no silent gaps — applied to a
  qualitative, multi-source corpus.

**Common thread across all three:** the same order of needs — *ingest
without per-source hassle → normalize into one shape → get answers out* —
just with different weight on the last step (PM wants the export, founder
wants the chatbot's synthesis, researcher wants the checkpointed corpus).

## 5. Jobs-to-be-done

> "When I have a list of links about a product from mixed sources, I want to
> turn them into one trustworthy table without manually visiting each one or
> reconciling different export formats, so I can compare, share, or query
> what people actually said — without wondering if a gap in the data is a
> real gap or a tool failure."

The second half of that sentence — trusting silence — is doing a lot of
work. It's why "fail loudly" and "nothing fabricated" (problem statement
§6) aren't secondary constraints; they're the actual value proposition next
to a generic scraper or an LLM summarizer that fills gaps with plausible
guesses.

## 6. What "done" looks like — walked through as a session

1. **Upload.** User pastes a mixed batch — a Play Store URL, two YouTube
   links, a Reddit thread — into one box. No pre-sorting by source. They
   can paste, bulk-paste, or upload a file (problem statement §5).
2. **Extract.** The app classifies each link by source, dispatches to the
   matching extractor, and works through the list with visible per-link
   progress. A failure on link #40 doesn't lose links #1–39 — extraction is
   resumable, not all-or-nothing (problem statement §4.2, §8).
3. **Normalize.** Every extracted document — a Play Store review, a Reddit
   comment, a YouTube comment — is mapped into one shared schema. This is
   the step that makes cross-source comparison possible; see §7 below for
   what that schema likely needs to hold.
4. **Export + Dashboard.** The normalized set downloads as Excel and is
   simultaneously browsable as a dashboard (volume, sentiment, source
   breakdown) with a chatbot scoped to *this batch's* data — grounded, not
   a general-purpose LLM answer, and willing to say "I don't have enough
   data for that" rather than guess (problem statement §3, §8).

Each stage is visible as its own step specifically so a long batch never
reads as a black box — the user should always be able to tell "we're on
link 40 of 200, extracting" versus "we're stuck."

## 7. The normalized schema (implied, not yet specified)

> **Superseded.** `ARCHITECTURE.md` §7 now defines the real schema. The
> sketch below was written before that existed and is kept only as a record
> of the reasoning; where the two differ, ARCHITECTURE.md wins. The main
> changes: `doc_type` and `parent_id` replace the speculative
> `parent_context` field (so Q&A pairs link natively), and `doc_id` hashes
> author alongside text so identical review bodies aren't collapsed.

The problem statement establishes *that* one schema must exist across all
four sources (§4.3) but doesn't define its fields — that belongs in the
follow-up spec. Based on what the dashboard, export, and chatbot all need
to do with the data, the schema almost certainly needs at minimum:

| Field | Notes |
|---|---|
| `source` | `play_store` \| `app_store` \| `youtube` \| `reddit` — drives dashboard's "source breakdown" chart |
| `source_url` | the original link the user pasted, for traceability back to raw evidence |
| `document_id` | stable id for dedup and for "re-running doesn't re-extract" (§8) |
| `author` (or anonymized handle) | present in all four sources in some form |
| `text` | the review/comment/post body — the field everything downstream (sentiment, chatbot) reads |
| `posted_at` | **nullable** — not all sources expose exact timestamps; per §6, absence must stay null, never guessed |
| `rating` | **nullable** — only Play/App Store reviews have this; Reddit/YouTube comments don't, and that's not a gap to fill |
| `parent_context` | app name / video title / thread title — needed so a Reddit comment and a Play Store review about the *same* product are comparably grouped |
| `extraction_tier` / `extractor_version` | **[inferred]** worth carrying through from the harvester's tier system (CLAUDE.md §2.3) for debuggability — if a field looks wrong later, knowing it came from a Tier C RPC-replay extractor versus a Tier A official-API path matters |
| `sentiment` | **not** raw-extracted — this is a derived field a normalization/analysis step must produce; see §9 below, this is the biggest unspecified piece of the whole pipeline |

The "sentiment" chart named in §5 of the problem statement is the one
dashboard element that has no extraction-time source — it has to be
computed. That computation step isn't described anywhere in the problem
statement and is worth flagging explicitly (see Risks, §9).

## 8. Scope, restated with intent

### In scope (v1) — and *why* each boundary sits where it does
- **Four sources only** (Play Store, App Store, YouTube, Reddit) — chosen
  because they're the highest-value review/comment surfaces *and* three of
  four already have a working extractor. This is a deliberate
  build-on-what-exists constraint, not a claim that these are the only
  sources worth having eventually (§5, §7).
- **Sequential, resumable extraction** — optimizes for "never lose progress
  on a long batch" over raw speed. §9 of the problem statement flags this
  as still open (sequential vs. bounded parallelism) — treat it as a real
  open decision, not settled.
- **One normalized schema** — the entire value proposition; see §7 above.
- **Excel export + dashboard + scoped chatbot** — three different
  consumption modes for the same normalized data, matching the three
  personas' different weightings (§4).

### Out of scope (v1) — and why these are hard lines, not soft ones
- **No auth bypass, paywall bypass, or captcha solving.** This isn't a v1
  cut for later — it's a permanent constraint carried from the extension's
  existing contract (CLAUDE.md §2.1) and restated here "without exception"
  (§5, §6). A follow-up spec should not treat this as negotiable scope.
- **No fifth source in v1**, but the adapter contract is designed so adding
  one is "one file, register it" (§5, §7) — worth preserving as a design
  constraint on whatever the follow-up spec builds, since it's the reason
  Reddit-with-no-existing-adapter isn't a blocker to shipping v1 with the
  other three.
- **No streaming, no multi-tenant, no accounts.** Single-operator research
  tool. This shapes a lot of otherwise-tempting architecture (queues, auth,
  per-user rate limit pools) *out* of v1 — worth stating explicitly so a
  build spec doesn't over-engineer for a multi-tenant future that isn't in
  scope.

## 9. Risks, gaps, and assumptions worth surfacing now

These aren't blockers — the problem statement is honest that architecture
is deferred — but each is a place where "done" (§3/§8 of the problem
statement) could quietly slip if not designed for explicitly.

1. **Sentiment is an unfunded mandate.** The dashboard promises a
   "sentiment" chart (§5) and the chatbot must answer grounded questions
   like "what do people complain about most" (§8) — both require a
   classification step over `text` that isn't named as an extractor,
   normalizer, or existing pipeline component anywhere in §7's prior art.
   The wishlist-census pipeline's "gate → structured extraction" steps
   (§7) are the closest existing analog and are the most likely candidate
   to generalize — but that's an assumption, not a stated fact.
   **[inferred]**
2. **Reddit has no adapter yet, and its tier is explicitly unresolved**
   (§9 of the problem statement, question 2). The `.json`-suffix endpoint
   is genuinely public and key-less, which is attractive under the
   free/low-cost and no-auth-bypass constraints (§6) — but until that's
   confirmed as sufficient (versus needing OAuth, which would collide with
   the no-login-automation rule), Reddit is the one source in v1 scope
   whose feasibility isn't yet proven, not just unbuilt.
3. **"Fail loudly" needs a defined failure taxonomy.** §6 promises a failed
   link is visible with a reason, never silently dropped — but "reason"
   needs categories (unreachable, unsupported format, rate-limited,
   extractor error, content removed) before a UI can render it usefully.
   Undefined today; worth resolving before the follow-up spec, not during
   implementation. **[inferred]**
4. **Checkpointing/re-run semantics need a concrete key.** §8 requires that
   re-running the same batch doesn't re-extract or re-charge anything
   already done. That requires a stable identity per link (or per
   extracted document) to check against — likely `source_url` normalized,
   or `document_id` per §7 above — and a persisted store of what's already
   been done. Not specified yet.
5. **"Free/low-cost by default" (§6) applies to the chatbot too**, and a
   grounded, clarify-before-answering chatbot (§7, §9 question 3) over a
   variable, mixed-source, user-supplied batch is a harder grounding
   problem than the wishlist-census chatbot's fixed single-dataset case.
   Worth scoping explicitly rather than assuming the existing
   `assistant.py` pattern ports over unchanged — the problem statement
   itself flags this as open (§9, question 3).
6. **Batch size and mixed-format upload edge cases are unstated.** §5 says
   "paste, bulk paste, or file upload" but doesn't bound batch size, or
   define what happens with duplicate links, malformed links, or links to
   unsupported sources mixed into an otherwise-valid batch. Given
   "sequential extraction" is the current default assumption, a very large
   batch has real wall-clock implications for the researcher persona in
   particular. **[inferred]**

## 10. Success criteria (from the problem statement, unchanged)

- 20 mixed links in → one Excel file out, every link represented as
  normalized rows, zero manual per-source cleanup.
- Every failed/unresolvable link is visible in run output with a reason.
- The chatbot answers grounded questions about the batch and explicitly
  declines rather than guesses when it lacks enough data.
- Re-running an identical batch is a no-op on already-completed work.

These four are the acceptance bar for v1 and translate directly into test
cases once a build spec exists — each is independently verifiable without
needing the full four-source set built out (e.g., success criterion 1 can
be tested with three working extractors while Reddit is still being
validated per Risk 2 above).

## 11. Open questions carried forward (from problem statement §9)

> **All four are now resolved in `ARCHITECTURE.md` §15.** Answers summarized
> below; that document is authoritative.

1. ~~Sequential extraction vs. bounded parallelism per source.~~
   **Resolved: bounded parallelism per source**, each with its own semaphore
   and token bucket (ARCHITECTURE.md §9.2).
2. ~~Reddit's extraction tier — does the `.json` endpoint suffice?~~
   **Resolved: it does not — `.json` returns 403 unauthenticated since May
   2026.** OAuth is mandatory. Crucially this does *not* conflict with the
   no-login-automation constraint: registering your own free API app is
   sanctioned first-party access, not automating anyone's login
   (ARCHITECTURE.md §2.3).
3. ~~Does the chatbot need new grounding logic for mixed-source batches?~~
   **Resolved: the clarify-before-answer pattern carries over**, with the
   cross-source-not-comparable caveat elevated to a hard rule
   (ARCHITECTURE.md §11).
4. ~~Single combined app vs. extension-feeds-pipeline.~~
   **Resolved: one standalone app.** A FastAPI orchestrator owns all three
   ingestion lanes; no browser-extension dependency (ARCHITECTURE.md §4).

## 12. Additional questions this synthesis surfaced

5. ~~What computes `sentiment`?~~ **Resolved:** a three-stage gate — lexical
   prefilter → local embedding similarity → LLM on the ambiguous band only —
   so most documents never reach a paid API (ARCHITECTURE.md §10.2).
6. ~~What's the failure taxonomy for "fail loudly"?~~ **Resolved:** eleven
   typed codes each carrying a `retryable` flag, plus `LANE_DOWNGRADE` as a
   first-class visible event (ARCHITECTURE.md §7.1).
7. ~~What's the checkpoint identity key?~~ **Resolved:**
   `doc_id = sha256(source | source_url | author_hash | normalize(text))`.
   Author is included deliberately so a thousand genuine "good app" reviews
   stay a thousand data points (ARCHITECTURE.md §7).
8. **Still open:** bounds on batch size, and the UX for a batch mixing valid
   with invalid/unsupported links.

### Still open after the architecture pass

- **`session_mode`** — ship `logged_out` (strictly within §6), or enable
  `operator_session` to unlock full Amazon reviews at the cost of amending
  §6. Recommendation is to defer until there's real data in hand.
- **Whether Amazon is worth the browser lane at all**, given only ~8–13
  featured reviews are publicly visible since May 2026.
- **Country/language fan-out policy** — both app stores cap per locale, so
  coverage is a deliberate multiplier on runtime.

## 13. Glossary

- **Tier (A/B/C/D)** — the harvester extension's classification of how a
  source is extracted, from most-sanctioned (official API) to least
  (RPC replay); referenced in CLAUDE.md §2.3, relevant to where Reddit
  lands (open question 2).
- **Normalize** — mapping any source's extracted document into the one
  shared schema (§7) so rows are directly comparable regardless of origin.
- **Grounded chatbot** — answers restricted to the extracted data for the
  specific uploaded batch, not general LLM knowledge; must decline when
  data is insufficient rather than produce a plausible-sounding guess.
- **Gate** (from the wishlist-census pipeline, §7) — a filtering step
  between normalization and structured extraction; likely relevant to
  however sentiment/theme classification ends up being scoped (§9.1).

## 14. What this document deliberately does not do

Per the problem statement's own framing, architecture and phased build
order are explicitly out of scope here and belong in a follow-up spec.
This document adds personas, journeys, an implied schema, and a risk list
— it does not pick sequential-vs-parallel extraction, decide Reddit's
tier, design the chatbot's grounding logic, or choose single-app-vs-
two-apps. Those four remain open exactly as the problem statement left
them (§11 above), now joined by four more surfaced in §12.

# PROBLEM_STATEMENT.md — AI Discovery Engine

> Status: draft, pre-build. This defines the WHAT and WHY. Architecture and
> phased build order belong in a separate spec once this is agreed — see
> "Relationship to existing work" for what already exists and doesn't need
> re-deciding.

---

## 1. The problem

Understanding what real people say about a product — across app stores,
video comments, and forums — currently means one of three bad options:

1. **Manual reading.** Doesn't scale past a handful of links. A researcher
   opening 40 Play Store pages and skimming reviews by hand cannot
   realistically process thousands of documents, and nothing they read is
   structured enough to aggregate, filter, or hand to someone else.
2. **A different tool per source.** One export flow for app store reviews,
   another for YouTube comments, another for Reddit threads — each with its
   own format, its own manual cleanup, no shared schema. Comparing "what do
   people say on Reddit" against "what do people say in Play Store reviews"
   means reconciling three spreadsheets by hand.
3. **A generic scraper.** Fast, but brittle (breaks on every site redesign),
   legally risky (no respect for auth boundaries or rate limits), and
   produces raw HTML/JSON nobody can act on without a second round of
   cleanup.

None of these produce what a researcher, PM, or founder actually wants:
**a single, structured, exportable table of what people said, where, and
when — built from links they choose, with nothing manual in the middle.**

## 2. Who has this problem

- A product manager evaluating a competitor: wants every public comment
  about a competing app across stores and YouTube, in one sheet, this week.
- A founder doing pre-launch research: wants to know what people complain
  about in adjacent apps before building.
- A researcher (this project's own use case — see §7) running a structured
  study: wants a labeled corpus, not a pile of raw text.

All three want the same three things, in this order: **get the data in
without per-source hassle → get it into one consistent shape → get it out
in a form they can actually use (a spreadsheet, a dashboard, or answers to
questions).**

## 3. What "done" looks like

A person pastes a batch of links — mixed sources, mixed formats — into one
box. They walk away. They come back to:

- every link resolved to its data, extracted automatically
- every document normalized to one schema regardless of source
- an Excel export, ready to hand to someone who has never seen this tool
- a dashboard they can click through, and a chatbot they can ask questions
  of in plain language, grounded in the actual extracted data — not a model
  guessing

## 4. Proposed app structure

Four stages, run in order, each visible as its own step so a long batch
never feels like a black box:

1. **Upload** — paste or bulk-upload a list of links. Mixed sources in one
   batch (a Play Store URL, a YouTube video URL, a Reddit thread, all in
   the same paste). No manual sorting by source required.
2. **Extract** — the app resolves each link to its source, runs the
   matching extractor, and works through the list **one link at a time**
   (or a bounded number in parallel — see §6 open questions), so
   progress is visible and a failure on link #40 doesn't lose links #1–39.
3. **Normalize** — every extracted document gets mapped into one shared
   schema regardless of where it came from, so a Play Store review and a
   Reddit comment are directly comparable rows, not two different shapes
   glued together after the fact.
4. **Export + Dashboard** — normalized data downloads as an Excel file, and
   is also browsable in a dashboard with charts and a chatbot that answers
   questions grounded in that specific batch's data (not a general-purpose
   LLM answer).

## 5. Scope

### In scope (v1)

- **Supported link types:** Play Store app pages, App Store app pages,
  YouTube videos, Reddit threads/posts. Four sources, chosen because
  they cover the highest-value review/comment surfaces and (per the
  existing harvester adapters — see §7) three of the four already have a
  working extraction path.
- Mixed-source batch upload (paste, bulk paste, or file upload).
- Sequential, resumable extraction with visible per-link progress.
- One normalized schema across all sources.
- Excel export.
- A dashboard with basic charts (volume, sentiment, source breakdown) and a
  chatbot scoped to the uploaded batch's data.

### Explicitly out of scope (v1)

- Any source requiring login, paywall bypass, or captcha solving — a hard
  line already established for this project (CLAUDE.md §2.1) and it
  carries forward here without exception.
- Sources beyond the four listed. Adding a fifth source should be a matter
  of writing one new extractor, not redesigning anything (see §7 — this is
  already how the underlying adapter contract works).
- Real-time/streaming extraction. Batches are finite and user-initiated.
- Multi-user accounts, permissions, or a hosted multi-tenant product. This
  is a single-operator research tool for now.

## 6. Constraints and principles

Carried forward from this project's existing work (CLAUDE.md, the browser
extension's own contract) because they're correct here too, not because
they're being reapplied by default:

- **No authentication bypass, no captcha solving, no login automation.**
  Capture only what's already publicly visible.
- **Free/low-cost by default.** Extraction and any LLM-backed steps
  (normalization assistance, the chatbot) should run on free tiers or
  local compute wherever possible — this is a research tool, not a funded
  product with an API budget.
- **Fail loudly, not silently.** A link that can't be resolved or extracted
  should show up as a visible failure in the run, never just vanish from
  the output with no explanation.
- **Nothing fabricated.** If a field isn't present in the source (a missing
  date, an unknown rating), it stays null. A guessed value that looks real
  is worse than a visible gap.
- **Polite by default.** Rate-limited, jittered requests — not because a
  captcha will stop the tool, but because that's the honest way to collect
  public data without being a nuisance to the source.

## 7. Relationship to existing work

This is not a fresh build — it's the next stage of two things already
built in this project:

- **The link harvester browser extension** (this repo, `CLAUDE.md`):
  already has working adapters for `play_store` (Tier C, RPC replay),
  `app_store` and `youtube` (Tier A/B), plus a generic Lane 2 fallback for
  anything else. Reddit is the one source named here with no adapter yet.
  The adapter contract (`CLAUDE.md` §4) is explicitly designed so adding a
  source is "one file, register it" — Reddit fits that pattern; it isn't a
  new architecture.
- **The wishlist-census labeling pipeline** (`dashboad-viwer` repo,
  `EXTRACTION_SPEC.md`): already does normalize → gate → structured
  extraction → DuckDB → Streamlit dashboard with a grounded chatbot
  (`census/assistant.py`), on free-tier compute, for one specific research
  question. The "normalize, export, dashboard, chatbot" half of this
  problem statement is largely that pipeline generalized to accept any
  supported link as input instead of one pre-harvested JSONL file.

The open design question this problem statement deliberately does **not**
answer yet: whether the "AI discovery engine" is these two pieces properly
joined into one app (extension or web app triggers ingestion → same
pipeline runs downstream), or a new front end that calls into both. That's
an architecture decision for the follow-up spec, not this document.

## 8. Success criteria

- A user can paste 20 mixed links (some Play Store, some YouTube, some
  Reddit) and get a single Excel file back with every one of them
  represented as normalized rows, with no manual per-source cleanup step.
- A failed/unresolvable link is visible in the run output with a reason,
  not silently dropped.
- The chatbot answers a question about the batch ("what do people complain
  about most") using only the extracted data, and says so when it doesn't
  have enough data to answer confidently — never a confident-sounding guess.
- Re-running the same batch doesn't re-extract or re-charge anything
  already done (this project's existing checkpointing discipline —
  EXTRACTION_SPEC.md's batching rule, and the gate/extract checkpointing
  fixed earlier in this project — applies here too).

## 9. Open questions (for the follow-up spec, not this document)

- Sequential extraction ("one by one," per the requested structure) vs.
  bounded parallelism per source — sequential is simplest and safest for
  rate limits, but slow on a large batch. Worth deciding explicitly rather
  than defaulting silently.
- Where does Reddit extraction fit tier-wise (A/B/C/D per CLAUDE.md §2.3) —
  does Reddit's public JSON endpoint (`.json` suffix on any thread URL)
  give Tier B access without an API key, or does a real solution need
  OAuth (which would put it up against the no-login-automation constraint)?
- Does the chatbot reuse `census/assistant.py`'s clarify-before-answer
  pattern as-is, or does a mixed-source batch need new grounding logic?
- Single combined app vs. extension-feeds-pipeline — see §7.

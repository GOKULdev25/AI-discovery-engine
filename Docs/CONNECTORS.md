# CONNECTORS.md — one page per source

> Updated at each phase that touches a connector. Endpoint, ceiling,
> cursor shape, and known failure modes — the facts a future debugging
> session needs first.

---

## App Store (`connectors/appstore.py`)

- **Endpoint:** `itunes.apple.com/{country}/rss/customerreviews/page={n}/id={app_id}/sortby=mostrecent/json`. No key.
- **Ceiling:** 500 reviews/country (10 pages x 50) — `MAX_PAGES = 10`. Widen via `expand()` fanning out over `project.yaml`'s `locales`.
- **Cursor:** page number, checkpointed after each page. Resume continues from the next page.
- **Stopping condition:** an empty page, or a page whose review IDs are a subset of the previous page's (Apple repeats the last real page past the end rather than erroring) — verified live, 2026-08-29.
- **Known failure modes:** malformed/non-JSON body → `PARSE_ERROR`; 404 (bad app id) → `NOT_FOUND` (generic `ctx.fetch()` mapping).
- **Live-verified (2026-08-29):** real reviews, ratings, dates for `com.facebook.katana` (`id284882215`). One country legitimately returned zero reviews at the time of the check — a real, momentary feed state, not a bug.

## Play Store (`connectors/playstore.py`)

- **Library:** `google-play-scraper` (wraps Google's unofficial `batchexecute` RPC) — synchronous, so it runs via `ctx.call_paced()` (rate-limited + `asyncio.to_thread`), not `ctx.fetch()`.
- **Ceiling:** none documented by Google; self-limited by politeness (heaviest jitter of the four connectors) and `MAX_PAGES = 50` (100/page).
- **Cursor:** `_ContinuationToken.token` (opaque string), checkpointed after each page; reconstructed on resume from the stored string plus the job's own `lang`/`country`/`sort`/`count` params.
- **Fan-out axis is language, not country** — verified live: `reviews()` with the same `lang` but different `country` returned byte-identical review IDs; different `lang` returned genuinely different reviews. `expand()` dedupes configured locales down to distinct languages before creating jobs (see `Docs/FEASIBILITY_LOG.md`, 2026-08-29).
- **Known failure modes:** the library raises plain `Exception`s with a message, not typed exceptions — `_classify()` pattern-matches the message text for "not found"/"404" → `NOT_FOUND`, else `NETWORK_ERROR`.

## YouTube (`connectors/youtube.py`)

- **Endpoint:** `googleapis.com/youtube/v3/commentThreads`, official Data API v3. Called directly via `ctx.fetch()` — the REST surface is simple enough that pulling in `google-api-python-client` wasn't worth the dependency.
- **Ceiling:** 10,000 units/day; ~1 unit per call regardless of `maxResults` (paginating at 100/page is what makes "~1 unit per 100 comments" hold, A§11.1).
- **Cursor:** `nextPageToken`, checkpointed after each page.
- **Known failure modes:** YouTube returns 403 for *both* a real auth problem and quota exhaustion and comments-disabled — `ctx.fetch()`'s generic 403→`AUTH_REQUIRED` mapping is deliberately reclassified in `_reclassify()` by inspecting the response body for `quotaExceeded`/`dailyLimitExceeded` (→ `QUOTA_EXHAUSTED`, retryable) and `commentsDisabled` (→ `EMPTY_RESULT`, not retryable). Getting this wrong would make quota exhaustion look like a permanent auth failure instead of "resumes tomorrow."
- **Not yet live-verified** — needs `YOUTUBE_API_KEY`; code-complete and covered by the offline eval suite (`EV-P1-04`, `EV-P1-11`) against recorded response shapes.

## Reddit (`connectors/reddit.py`)

- **Library:** `asyncpraw`, OAuth via app `client_id`/`client_secret` — **mandatory**, `.json` has 403'd unauthenticated since May 2026 (A§2.3). No username/password field exists anywhere in this file (EV-P-1-05).
- **Ceiling:** 100 QPM (non-commercial). `ctx.call_paced_async()` routes every call through this project's global per-source limiter — asyncpraw's own internal rate limiting is scoped to its own client instance and would not otherwise be shared across projects (A§10.2, EV-P1-09).
- **Cursor:** none in the paginated sense — a submission's comment tree is fetched as a unit via `replace_more(limit=32)` (a deliberate cap — "walk MoreComments deliberately, not blindly," IP§1.2) followed by `comments.list()`. `ctx.checkpoint()` is called every 50 comments as a heartbeat only, not a resume position — the list order isn't guaranteed stable enough across runs to make skip-by-ordinal safe, and doc_id idempotency already absorbs any redone work on a real crash.
- **Structure preserved:** the post is emitted as `doc_type="post"`, each comment as `doc_type="comment"` with `parent_id` pointing at its immediate parent's `doc_id` (post or comment), reconstructed from Reddit's own `t1_`/`t3_` fullnames as the tree is walked.
- **Known bug found and fixed (2026-08-29):** `reddit.submission(url=..., fetch=True)` — the default — already awaits the fetch internally; an explicit `.load()` afterward silently performed a second, redundant request per thread. Removed.
- **Not yet live-verified** — needs a Reddit app registration; code-complete and covered by the offline eval suite (`EV-P1-11`) against a fake `asyncpraw.Reddit` standing in for the real OAuth client.

## Flipkart (`browser/sites/flipkart.py`) — Lane 2, 🟢

- **Mechanism:** a real, persistent Chrome profile (`browser/session.py`), not an API — no stable JSON endpoint exists for reviews (live investigation, 2026-08-30: `window.__INITIAL_STATE__`'s review widgets are empty at load time, no XHR carries review content). Reads `page.inner_text()`'s rendered text via `browser/text_extract.py`'s pattern parsers — zero CSS/XPath selectors (`EV-P6-02`).
- **Ceiling:** none documented; human-paced via the shared `browser` rate spec (`concurrency=1`, 3-8s jitter, `jobs/limits.py`), `MAX_PAGES = 20`.
- **Cursor:** `&page=N` on the reviews URL — an unverified guess confirmed live (121 documents across multiple real pages); guarded by a same-first-review-signature stop check in case it stops working.
- **Q&A (P7, Amber):** the product page's own "Questions and Answers" preview widget, not a separate page or URL — most products have none; `parse_qa_from_text()` scopes to the widget's initial preview only, since its "Show all" control opens in place rather than navigating and proved unreliable to click through live.
- **Known failure modes:** `net::ERR_HTTP2_PROTOCOL_ERROR` observed live under headless Chrome specifically (real headful Chrome reached the same URL cleanly) → `NETWORK_ERROR`, retryable, deliberately not `BLOCKED_ANTIBOT` (ambiguous signal). Explicit 403/429 → `BLOCKED_ANTIBOT`.
- **Live-verified**, 2026-08-30.

## Amazon (`browser/sites/amazon.py`) — Lane 2, 🟡

- **Mechanism:** same persistent-profile approach as Flipkart; `/product-reviews/<ASIN>/` shows a sign-in wall to a `logged_out` session, so this connector only reads the featured reviews embedded on the product page itself.
- **Ceiling:** the `logged_out` session's structural ceiling — measured live at 7, 8, and 8 reviews across three real products (`Docs/DECISIONS.md` A§16.2), inside the plan's stated 8-13 range.
- **Cursor:** none — one product page, one pass.
- **Known failure modes:** same `NETWORK_ERROR`/`BLOCKED_ANTIBOT` split as Flipkart. No reviews on the page → `EMPTY_RESULT` with `raw.logged_out_ceiling: true`, an honest ceiling, not a bug.
- **Live-verified**, 2026-08-30.

## Myntra (`browser/sites/myntra.py`) — Lane 2, best-effort

- **Mechanism:** same persistent-profile approach; PerimeterX runs per-site behavioural models here (A§5.4, "deliberately declined" — no fingerprint spoofing, no proxy rotation, no captcha solving).
- **Ceiling:** none reached in live testing — browsing a category listing and three product pages logged-out did not trigger a block within the session's test budget, but no recognizable review section was found in the rendered text either.
- **Known failure modes:** explicit 403/429 or a block-page text marker (`px-captcha`, "verify you are a human", etc.) → `BLOCKED_ANTIBOT`, exactly once, never retried. No recognized review content → `EMPTY_RESULT`, never a guessed parser for a format never actually observed.
- **Live-verified**, 2026-08-30 (no block encountered; no reviews extracted).

## LLM-DOM fallback (`fallback/llm_dom.py`) — Lane 3, last resort

- **Mechanism:** the only connector with no fixed target site — matches any `http(s)` URL no earlier connector claimed (declines binary-asset extensions). `ctx.fetch()` the page, `selectolax` strips it to visible text (never a selector-based extraction), then a JSON-schema prompt to the same Gemini→Groq→Ollama failover chain Phase 3 classification uses (`ai/router.py`).
- **Ceiling:** `MAX_TEXT_CHARS = 40_000` per page (A§11.1 token budget); global `llm_dom` rate spec (`concurrency=2`, `jobs/limits.py`) shared across every distinct arbitrary domain this lane ever touches, since the limiter key is the connector id, not the target site.
- **Cursor:** none — one page, one pass; no pagination guess is possible for an unknown site.
- **Caching:** page-text-content-hash + `PROMPT_VERSION` keyed, via the same `ai/cache.py` every classification call uses — a retried extraction of the same page never re-spends a request.
- **Known failure modes:** every field but `text` is nullable in the schema and the prompt states an empty result is valid — a page with nothing extractable is `EMPTY_RESULT`, never a fabricated row (`EV-P7-02`, the system's single easiest place to fabricate data). Every provider exhausted → `QUOTA_EXHAUSTED`. An unparseable provider response → `PARSE_ERROR`.
- **Not live-verified against a real page** — offline-only in the automatic suite by design (`EV-INV-14`); code-complete and covered by `EV-P7-01/02/03/05/06` against a scripted fake provider.

## Fixture (`connectors/_fixture.py`)

Not a real source — the job engine's permanent test harness (IP§0.8). Matches `fixture://...`, emits N synthetic docs with configurable latency and a configurable failure at document K. Stays in the repo forever.

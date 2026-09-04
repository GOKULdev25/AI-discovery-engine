/**
 * The one place that turns backend enums into human language.
 *
 * These labels previously lived in two places that disagreed:
 * `ProjectDetailClient` showed "No connector for this source" while the
 * dashboard printed the raw `UNSUPPORTED_SOURCE`. "Fail loudly" (P§8) means a
 * failure has to be *legible*, not just present, so there is exactly one
 * mapping now and every surface reads it.
 */

/** A§8.1's failure taxonomy, in the words an operator would actually use. */
export const FAILURE_LABELS: Record<string, string> = {
  INVALID_URL: "Not a valid URL",
  UNSUPPORTED_SOURCE: "No connector for this source",
  NOT_FOUND: "Not found",
  AUTH_REQUIRED: "Behind a login",
  BLOCKED_ANTIBOT: "Blocked by the site",
  PARSE_ERROR: "Couldn't parse the response",
  EMPTY_RESULT: "No content found",
  EXTRACTOR_CRASH: "Extractor crashed",
  RATE_LIMITED: "Rate limited",
  QUOTA_EXHAUSTED: "AI quota exhausted",
  NETWORK_ERROR: "Network error",
};

/** One line of "what do I do about it", shown under a failure in batch detail. */
export const FAILURE_HINTS: Record<string, string> = {
  INVALID_URL: "Check the link was pasted in full.",
  UNSUPPORTED_SOURCE: "This URL shape has no extractor — Lane 3 declined it too.",
  NOT_FOUND: "The page returned 404 — it may have been removed.",
  AUTH_REQUIRED: "The content sits behind a sign-in wall this project can't cross.",
  BLOCKED_ANTIBOT: "The site actively refused. Not retried by design — no evasion.",
  PARSE_ERROR: "The source's format may have changed since this extractor shipped.",
  EMPTY_RESULT: "The page loaded but genuinely had no reviews on it.",
  EXTRACTOR_CRASH: "A bug in the extractor — worth reporting.",
  RATE_LIMITED: "Backed off automatically; retry when the window resets.",
  QUOTA_EXHAUSTED: "Today's free-tier budget is spent. Resets tomorrow.",
  NETWORK_ERROR: "A transient connection problem. Safe to retry.",
};

export function failureLabel(code: string | null | undefined): string {
  if (!code) return "Failed";
  return FAILURE_LABELS[code] ?? code;
}

/**
 * Retryable failures (A§8.1) are a softer signal than terminal ones — the run
 * didn't fail so much as pause. Terminal ones are the ones a human must act on.
 */
export const RETRYABLE_CODES = new Set([
  "RATE_LIMITED",
  "QUOTA_EXHAUSTED",
  "NETWORK_ERROR",
]);

/* -------------------------------------------------------------------------- */

export const SOURCE_LABELS: Record<string, string> = {
  playstore: "Play Store",
  appstore: "App Store",
  youtube: "YouTube",
  reddit: "Reddit",
  flipkart: "Flipkart",
  amazon: "Amazon",
  myntra: "Myntra",
  llm_dom: "Other (LLM-read)",
  fixture: "Fixture",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * Chart colours resolve to CSS custom properties rather than literal hex, so a
 * theme switch retints every chart with no React re-render and no JS at all.
 * SVG `fill`/`stroke` accept `var()` natively.
 */
const SOURCE_COLOR_VARS: Record<string, string> = {
  playstore: "--src-playstore",
  appstore: "--src-appstore",
  youtube: "--src-youtube",
  reddit: "--src-reddit",
  flipkart: "--src-flipkart",
  amazon: "--src-amazon",
  myntra: "--src-myntra",
  llm_dom: "--src-llm-dom",
  fixture: "--src-fixture",
};

export function sourceColor(source: string): string {
  return `var(${SOURCE_COLOR_VARS[source] ?? "--src-fixture"})`;
}

export const SENTIMENT_BUCKETS = ["positive", "neutral", "negative", "unknown"] as const;

const SENTIMENT_BUCKET_SET: ReadonlySet<string> = new Set(SENTIMENT_BUCKETS);

export function sentimentColor(bucket: string): string {
  const known = SENTIMENT_BUCKET_SET.has(bucket) ? bucket : "unknown";
  return `var(--sent-${known})`;
}

/* -------------------------------------------------------------------------- */

/**
 * A§4's three lanes. Surfacing this is a correctness requirement, not decoration:
 * a Lane 3 (`llm_dom`) row is explicitly lower-confidence than a Lane 1 API row,
 * and the plan requires that be *visible* rather than blended away.
 */
export const LANE_LABELS: Record<string, string> = {
  api: "API",
  browser: "Browser",
  llm_dom: "LLM-read",
};

export const LANE_DESCRIPTIONS: Record<string, string> = {
  api: "Read from an official API — highest confidence.",
  browser: "Read from a real browser session — high confidence.",
  llm_dom: "An LLM read this page's text. Lower confidence than a purpose-built extractor.",
};

export function laneLabel(lane: string | null | undefined): string {
  if (!lane) return "—";
  return LANE_LABELS[lane] ?? lane;
}

export const GATE_BAND_LABELS: Record<string, string> = {
  keep: "Kept",
  drop: "Dropped",
  ambiguous: "Ambiguous",
};

/* -------------------------------------------------------------------------- */

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "just now" / "4m ago" / "3h ago", falling back to a date past a week. */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 45) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  if (secs < 604800) return `${Math.round(secs / 86400)}d ago`;
  return formatDate(value);
}

export function formatCount(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

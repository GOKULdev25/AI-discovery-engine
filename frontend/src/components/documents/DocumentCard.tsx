"use client";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import type { SourceProfile } from "@/lib/sourceProfiles";
import {
  GATE_BAND_LABELS,
  LANE_DESCRIPTIONS,
  formatDate,
  laneLabel,
  sourceColor,
  sourceLabel,
} from "@/lib/labels";

export type Doc = {
  doc_id: string;
  source: string;
  doc_type: string;
  source_url: string;
  subject: string | null;
  captured_at: string | null;
  authored_at: string | null;
  text: string | null;
  lang: string | null;
  rating: number | null;
  verified_purchase: boolean | null;
  sentiment_prior: number | null;
  gate_band: string | null;
  lane?: string | null;
  extractor_version?: string | null;
  product_id?: string | null;
  variant?: string | null;
  parent_id?: string | null;
  engagement?: Record<string, unknown> | null;
  engagement_count?: number | null;
  engagement_kind?: string | null;
};

/** Filled/empty stars, with the numeric value beside them — the shape is a
 *  fast scan, the number is the fact. Never stars alone. */
function Stars({ value, scale }: { value: number; scale: number }) {
  const rounded = Math.round(value);
  return (
    <span className="inline-flex items-center gap-1" title={`${value} of ${scale}`}>
      <span aria-hidden className="tracking-tight text-warn">
        {"★".repeat(Math.min(rounded, scale))}
        <span className="text-line-strong">
          {"★".repeat(Math.max(scale - rounded, 0))}
        </span>
      </span>
      <span className="tnum text-fg-muted">
        {value.toFixed(1)}
        <span className="sr-only"> out of {scale}</span>
      </span>
    </span>
  );
}

/**
 * One document, rendered as the kind of thing it actually is.
 *
 * Every source used to draw in an identical table row with a Rating column
 * that read "—" for sources that have no ratings, while the fields that
 * would have distinguished them — an App Store review's title, a Reddit
 * thread, a like count, a reply's parent — were captured and never shown.
 * Which affordances appear here is decided by the source's own profile, so
 * a field is only ever drawn where it exists.
 */
export function DocumentCard({
  doc,
  profile,
  onOpen,
  compact,
}: {
  doc: Doc;
  profile: SourceProfile;
  onOpen: () => void;
  compact?: boolean;
}) {
  const showSubject = profile.subject_label !== null && !!doc.subject;
  const showRating = profile.rating !== null && doc.rating != null;
  const showEngagement = doc.engagement_count != null;
  const showVerified =
    profile.verified_purchase && doc.verified_purchase != null;
  const isReply = !!doc.parent_id;

  return (
    <article
      onClick={onOpen}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "cursor-pointer border-b border-line/60 px-5 py-3.5 transition-colors last:border-0 hover:bg-surface-hover",
        isReply && "border-l-2 bg-surface-sunken/40 pl-8"
      )}
      style={isReply ? { borderLeftColor: sourceColor(doc.source) } : undefined}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {isReply && (
            <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-fg-subtle">
              ↳ Reply
            </p>
          )}
          {showSubject && (
            <p className="mb-0.5 truncate text-sm font-semibold text-fg">
              {doc.subject}
            </p>
          )}
          <p
            className={cn(
              "text-sm text-fg",
              compact ? "truncate" : "line-clamp-3 whitespace-pre-wrap"
            )}
          >
            {doc.text ?? "—"}
          </p>
        </div>
        <time className="tnum shrink-0 text-[11px] text-fg-subtle">
          {formatDate(doc.authored_at ?? doc.captured_at)}
        </time>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]">
        <span className="inline-flex items-center gap-1.5 text-fg-muted">
          <span
            aria-hidden
            className="size-2 rounded-[2px]"
            style={{ background: sourceColor(doc.source) }}
          />
          {sourceLabel(doc.source)}
        </span>

        {showRating && profile.rating && (
          <Stars value={doc.rating!} scale={profile.rating.scale} />
        )}

        {showEngagement && (
          <span className="tnum text-fg-muted">
            ▲ {doc.engagement_count!.toLocaleString()}{" "}
            <span className="text-fg-subtle">
              {profile.engagement?.label.toLowerCase() ?? doc.engagement_kind}
            </span>
          </span>
        )}

        {showVerified && (
          <span
            className={
              doc.verified_purchase ? "text-success" : "text-fg-subtle"
            }
          >
            {doc.verified_purchase ? "✓ Verified purchase" : "Unverified"}
          </span>
        )}

        {doc.variant && profile.variant_label && (
          <span className="text-fg-subtle">
            {profile.variant_label}: {doc.variant}
          </span>
        )}

        {typeof doc.engagement?.app_version === "string" && (
          <span className="text-fg-subtle">v{doc.engagement.app_version}</span>
        )}

        <span className="ml-auto flex items-center gap-2">
          {doc.gate_band && (
            <span
              className={cn(
                doc.gate_band === "drop" && "text-fg-subtle",
                doc.gate_band === "keep" && "text-success",
                doc.gate_band === "ambiguous" && "text-warn"
              )}
            >
              {GATE_BAND_LABELS[doc.gate_band] ?? doc.gate_band}
            </span>
          )}
          <Badge
            tone={doc.lane === "llm_dom" ? "warn" : "neutral"}
            title={doc.lane ? LANE_DESCRIPTIONS[doc.lane] : undefined}
          >
            {laneLabel(doc.lane)}
          </Badge>
        </span>
      </div>
    </article>
  );
}

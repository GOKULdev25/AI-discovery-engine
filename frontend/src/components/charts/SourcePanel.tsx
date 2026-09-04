"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { AXIS, BarList, ChartTooltip } from "./chrome";
import type { SourceProfile } from "@/lib/sourceProfiles";
import {
  SENTIMENT_BUCKETS,
  formatDate,
  laneLabel,
  sentimentColor,
  sourceColor,
} from "@/lib/labels";

export type NamedCount = { name: string; doc_count: number };

export type SourceBlock = {
  source: string;
  label: string;
  doc_count: number;
  captured_from: string | null;
  captured_to: string | null;
  doc_types: NamedCount[];
  volume: NamedCount[];
  lanes: NamedCount[];
  languages: NamedCount[];
  sentiment_prior_breakdown: NamedCount[];
  ratings: { rating: number; doc_count: number }[];
  rating_coverage: number;
  rating_scale: number | null;
  engagement: {
    kind: string;
    label: string;
    covered: number;
    total: number;
    max: number;
    mean: number;
    buckets: NamedCount[];
  } | null;
};

const SENTIMENT_LABELS: Record<string, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
  unknown: "No signal",
};

/**
 * A panel showing one source, with only the charts that source actually
 * has data for.
 *
 * Every block states its own denominator. Where a field is declared by the
 * profile but unpopulated ("ratings on 0 of 349"), that fact is written out
 * rather than drawn as an empty chart — a zeroed chart reads as a finding
 * (EV-P4-07), a stated zero reads as a gap.
 */
export function SourcePanel({
  block,
  profile,
}: {
  block: SourceBlock;
  profile: SourceProfile;
}) {
  const accent = sourceColor(block.source);
  const hasRatings = profile.rating !== null;
  const ratingsPresent = block.ratings.length > 0;

  const sentiment = SENTIMENT_BUCKETS.map((b) => ({
    name: b,
    label: SENTIMENT_LABELS[b] ?? b,
    doc_count:
      block.sentiment_prior_breakdown.find((s) => s.name === b)?.doc_count ?? 0,
  })).filter((s) => s.doc_count > 0);

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            <span
              aria-hidden
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: accent }}
            />
            {block.label}
            <Badge tone="neutral">
              {block.doc_count.toLocaleString()} documents
            </Badge>
            {block.doc_types.map((t) => (
              <Badge key={t.name} tone="neutral">
                {t.name.replace(/_/g, " ")} · {t.doc_count.toLocaleString()}
              </Badge>
            ))}
          </span>
        }
        description={
          <>
            {block.captured_from && block.captured_to
              ? `Captured ${formatDate(block.captured_from)} – ${formatDate(block.captured_to)}`
              : "No capture window"}
            {profile.notes ? ` · ${profile.notes}` : ""}
          </>
        }
      />

      <CardBody className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
        {/* Ratings — only for sources whose profile declares them. */}
        {hasRatings && (
          <section>
            <h3 className="mb-1 text-xs font-medium text-fg">
              {profile.rating?.label ?? "Rating"} distribution
            </h3>
            <p className="mb-2 text-[11px] text-fg-subtle">
              {block.rating_coverage.toLocaleString()} of{" "}
              {block.doc_count.toLocaleString()} documents carry a rating
            </p>
            {ratingsPresent ? (
              <ResponsiveContainer width="100%" height={170}>
                <BarChart
                  data={block.ratings}
                  margin={{ top: 4, right: 4, bottom: 0, left: -22 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="rating" {...AXIS} />
                  <YAxis allowDecimals={false} {...AXIS} />
                  <Tooltip
                    cursor={{ fill: "var(--surface-hover)" }}
                    content={<ChartTooltip />}
                  />
                  <Bar
                    dataKey="doc_count"
                    name="Documents"
                    fill={accent}
                    maxBarSize={44}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="rounded-lg border border-dashed border-line px-3 py-4 text-xs text-fg-subtle">
                No document from this source carried a rating.
              </p>
            )}
          </section>
        )}

        {/* Engagement — the number this source actually uses, never blended
            with another source's. */}
        {block.engagement && (
          <section>
            <h3 className="mb-1 text-xs font-medium text-fg">
              {block.engagement.label}
            </h3>
            <p className="mb-2 text-[11px] text-fg-subtle">
              {block.engagement.total.toLocaleString()} total · max{" "}
              {block.engagement.max.toLocaleString()} · mean{" "}
              {block.engagement.mean.toLocaleString()} · on{" "}
              {block.engagement.covered.toLocaleString()} of{" "}
              {block.doc_count.toLocaleString()}
            </p>
            <BarList
              items={block.engagement.buckets.map((b) => ({
                ...b,
                label: b.name === "0" ? "0" : b.name,
              }))}
              total={block.engagement.covered}
              colorFor={() => accent}
              emptyLabel="No engagement recorded."
            />
          </section>
        )}

        {/* Sentiment prior — labelled as a lexicon prior everywhere it
            appears, never as "sentiment" (EV-P4-05). */}
        <section>
          <h3 className="mb-1 text-xs font-medium text-fg">
            Sentiment (lexicon prior)
          </h3>
          <p className="mb-2 text-[11px] text-fg-subtle">
            A VADER word-list score, not a judgement of meaning
          </p>
          <BarList
            items={sentiment}
            total={block.doc_count}
            colorFor={(n) => sentimentColor(n)}
            emptyLabel="No documents scored."
          />
        </section>

        {/* Language — genuinely useful and previously invisible. */}
        {block.languages.length > 0 && (
          <section>
            <h3 className="mb-1 text-xs font-medium text-fg">Language</h3>
            <p className="mb-2 text-[11px] text-fg-subtle">
              Detected locally; low-confidence guesses stay unknown
            </p>
            <BarList
              items={block.languages.slice(0, 6).map((l) => ({
                ...l,
                label: l.name === "unknown" ? "Undetected" : l.name,
              }))}
              total={block.doc_count}
              colorFor={() => accent}
            />
          </section>
        )}

        {/* Lane — provenance is never optional (A§8). */}
        {block.lanes.length > 0 && (
          <section>
            <h3 className="mb-1 text-xs font-medium text-fg">
              How it was collected
            </h3>
            <p className="mb-2 text-[11px] text-fg-subtle">
              Lane 3 rows are lower confidence than an API row
            </p>
            <BarList
              items={block.lanes.map((l) => ({
                ...l,
                label: laneLabel(l.name),
              }))}
              total={block.doc_count}
              colorFor={() => accent}
            />
          </section>
        )}
      </CardBody>
    </Card>
  );
}

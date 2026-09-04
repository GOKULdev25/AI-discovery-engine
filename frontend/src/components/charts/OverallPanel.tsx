"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Alert, EmptyState } from "@/components/ui/Feedback";
import { AXIS, BAR_SEPARATION, BarList, ChartTooltip } from "./chrome";
import type { SourceBlock } from "./SourcePanel";
import { formatDate, sourceColor, sourceLabel } from "@/lib/labels";

/**
 * The all-sources view.
 *
 * It deliberately carries NO ratings and NO engagement. A 5-star App Store
 * rating and a Flipkart rating come from different populations with
 * different selection biases; a YouTube like, a Reddit upvote and an Amazon
 * helpful-vote are not one quantity. Stacking or averaging either across
 * sources would be exactly the "fabrication by aggregation" the Phase 4
 * gate warns about, so both live in per-source panels only.
 *
 * What remains here is what genuinely compares: how much was collected,
 * from where, when, and of what type.
 */
export function OverallPanel({
  blocks,
  mixedSource,
  capturedFrom,
  capturedTo,
  documentCount,
}: {
  blocks: SourceBlock[];
  mixedSource: boolean;
  capturedFrom: string | null;
  capturedTo: string | null;
  documentCount: number;
}) {
  // Pivot per-source daily counts into one row per day, one series per
  // source — never merged into a single undifferentiated bar (EV-P4-04).
  const volume = useMemo(() => {
    const byDay = new Map<string, Record<string, number | string>>();
    for (const b of blocks) {
      for (const point of b.volume) {
        const day = point.name.slice(0, 10);
        const row = byDay.get(day) ?? { day };
        row[b.source] = ((row[b.source] as number) ?? 0) + point.doc_count;
        byDay.set(day, row);
      }
    }
    return [...byDay.values()].sort((a, b) =>
      String(a.day).localeCompare(String(b.day))
    );
  }, [blocks]);

  const sources = blocks.map((b) => b.source);

  const docTypes = useMemo(() => {
    const totals = new Map<string, number>();
    for (const b of blocks) {
      for (const t of b.doc_types) {
        totals.set(t.name, (totals.get(t.name) ?? 0) + t.doc_count);
      }
    }
    return [...totals.entries()]
      .map(([name, doc_count]) => ({ name, doc_count }))
      .sort((a, b) => b.doc_count - a.doc_count);
  }, [blocks]);

  if (documentCount === 0) {
    return (
      <Card>
        <CardBody>
          <EmptyState
            title="No documents yet"
            description="Run a batch on the Extract tab and the charts will fill in."
          />
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {mixedSource && (
        <Alert tone="warn" title="Mixed sources">
          This project holds documents from {blocks.length} sources. Volume and
          document counts compare across them; ratings and engagement do not,
          so those appear only on each source&rsquo;s own panel below.
        </Alert>
      )}

      <Card>
        <CardHeader
          title="Volume over time"
          description={
            capturedFrom && capturedTo
              ? `${documentCount.toLocaleString()} documents captured ${formatDate(capturedFrom)} – ${formatDate(capturedTo)}`
              : `${documentCount.toLocaleString()} documents`
          }
        />
        <CardBody>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart
              data={volume}
              margin={{ top: 4, right: 4, bottom: 0, left: -20 }}
            >
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="day" {...AXIS} />
              <YAxis allowDecimals={false} {...AXIS} />
              <Tooltip
                cursor={{ fill: "var(--surface-hover)" }}
                content={<ChartTooltip />}
              />
              {sources.length > 1 && (
                <Legend
                  wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                  iconType="square"
                  iconSize={9}
                  // Recharts paints legend labels in the series colour,
                  // which put 11px text at 2.8:1 on the page. The swatch
                  // beside it already carries the identity; the words wear
                  // a text token so they stay readable in both themes.
                  formatter={(value) => (
                    <span style={{ color: "var(--fg-muted)" }}>{value}</span>
                  )}
                />
              )}
              {sources.map((s, i) => (
                <Bar
                  key={s}
                  dataKey={s}
                  name={sourceLabel(s)}
                  stackId="volume"
                  fill={sourceColor(s)}
                  maxBarSize={44}
                  radius={i === sources.length - 1 ? [4, 4, 0, 0] : undefined}
                  {...BAR_SEPARATION}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </CardBody>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader
            title="Where documents came from"
            description="Share of the whole project"
          />
          <CardBody>
            <BarList
              items={blocks.map((b) => ({
                name: b.source,
                label: b.label,
                doc_count: b.doc_count,
              }))}
              total={documentCount}
              colorFor={(n) => sourceColor(n)}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="What kind of document"
            description="Comparable across sources — a review and a comment are both one document"
          />
          <CardBody>
            <BarList
              items={docTypes.map((t) => ({
                ...t,
                label: t.name.replace(/_/g, " "),
              }))}
              total={documentCount}
            />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

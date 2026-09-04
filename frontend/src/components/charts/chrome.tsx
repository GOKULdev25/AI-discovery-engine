"use client";

import type { ReactNode } from "react";

/**
 * Shared chart chrome. Extracted from `DashboardClient` so the per-source
 * panels and the all-sources panel render identically rather than each
 * growing its own tooltip and axis styling.
 */

/** Recharts' default tooltip is a hardcoded white box — invisible-ish in dark
 *  mode and off-system in light. This one wears the app's own tokens. */
export function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface-raised px-3 py-2 shadow-[var(--shadow-pop)]">
      {label != null && (
        <p className="mb-1 text-[11px] font-medium text-fg">{String(label)}</p>
      )}
      <ul className="flex flex-col gap-0.5">
        {payload.map((entry, i) => (
          <li key={i} className="flex items-center gap-2 text-[11px]">
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-[2px]"
              style={{ background: entry.color }}
            />
            <span className="text-fg-muted">{entry.name}</span>
            <span className="tnum ml-auto font-medium text-fg">
              {entry.value?.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const AXIS = {
  tick: { fontSize: 11, fill: "var(--fg-subtle)" },
  axisLine: { stroke: "var(--line)" },
  tickLine: false,
} as const;

/** A 2px ring in the surface colour separates adjacent/stacked fills. */
export const BAR_SEPARATION = {
  stroke: "var(--surface)",
  strokeWidth: 2,
} as const;

export function StatTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "danger";
}) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3.5 shadow-[var(--shadow-card)]">
      <p className="text-[11px] font-medium uppercase tracking-wide text-fg-subtle">
        {label}
      </p>
      {/* A div, not a p: `value` may be a Skeleton block while loading, and a
          block element inside <p> is invalid HTML (React 19 flags it as a
          hydration error). */}
      <div
        className={
          "tnum mt-1.5 text-2xl font-semibold tracking-tight " +
          (tone === "danger" ? "text-danger" : "text-fg")
        }
      >
        {value}
      </div>
      {hint && <p className="mt-0.5 text-[11px] text-fg-muted">{hint}</p>}
    </div>
  );
}

/**
 * A labelled horizontal bar list. Used wherever a categorical breakdown
 * would otherwise become a pie — the label and the number are always
 * legible, and colour is never the only channel carrying identity.
 */
export function BarList({
  items,
  total,
  colorFor,
  emptyLabel = "None",
}: {
  items: { name: string; label?: string; doc_count: number }[];
  total: number;
  colorFor?: (name: string) => string;
  emptyLabel?: string;
}) {
  if (items.length === 0) {
    return <p className="text-xs text-fg-subtle">{emptyLabel}</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => {
        const pct = total > 0 ? (item.doc_count / total) * 100 : 0;
        return (
          <li key={item.name} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="truncate text-fg-muted">
                {item.label ?? item.name}
              </span>
              <span className="tnum shrink-0 font-medium text-fg">
                {item.doc_count.toLocaleString()}
                <span className="ml-1.5 font-normal text-fg-subtle">
                  {pct.toFixed(pct < 10 ? 1 : 0)}%
                </span>
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(pct, 1.5)}%`,
                  background: colorFor?.(item.name) ?? "var(--accent)",
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

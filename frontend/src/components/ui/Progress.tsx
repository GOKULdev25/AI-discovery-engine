import { cn } from "./cn";

export type ProgressSegment = {
  value: number;
  /** A CSS colour (token `var(--x)` is fine) for this slice of the bar. */
  color: string;
  label: string;
};

/**
 * A segmented progress bar: done / failed / running / pending in one track.
 *
 * Deliberately not a single percentage — "fail loudly" (P§8) means a batch that
 * is 90% complete with 10% failed must not read as a healthy 90% bar. The
 * failed slice is always visible and always its own colour.
 */
export function SegmentedProgress({
  segments,
  total,
  className,
  label,
}: {
  segments: ProgressSegment[];
  total: number;
  className?: string;
  label?: string;
}) {
  const safeTotal = Math.max(total, 1);
  return (
    <div
      className={cn("h-1.5 w-full rounded-full bg-surface-sunken overflow-hidden flex", className)}
      role="progressbar"
      aria-label={label ?? "Progress"}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={segments.reduce((sum, s) => sum + s.value, 0)}
    >
      {segments
        .filter((s) => s.value > 0)
        .map((s) => (
          <div
            key={s.label}
            title={`${s.label}: ${s.value}`}
            style={{
              width: `${(s.value / safeTotal) * 100}%`,
              backgroundColor: s.color,
            }}
            className="h-full transition-[width] duration-500 ease-out"
          />
        ))}
    </div>
  );
}

/** A slim meter for a quota/budget reading. */
export function Meter({
  used,
  limit,
  tone = "accent",
  className,
}: {
  used: number;
  limit: number;
  tone?: "accent" | "warn" | "danger";
  className?: string;
}) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const fill =
    tone === "danger" ? "bg-danger" : tone === "warn" ? "bg-warn" : "bg-accent";
  return (
    <div
      className={cn("h-1 w-full rounded-full bg-surface-sunken overflow-hidden", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={limit}
      aria-valuenow={used}
    >
      <div className={cn("h-full rounded-full transition-[width] duration-500", fill)} style={{ width: `${pct}%` }} />
    </div>
  );
}

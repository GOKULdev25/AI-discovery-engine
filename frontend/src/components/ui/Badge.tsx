import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

export type Tone = "neutral" | "accent" | "success" | "warn" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-sunken text-fg-muted border-line",
  accent: "bg-accent-soft text-accent border-accent-line",
  success: "bg-success-soft text-success border-success-line",
  warn: "bg-warn-soft text-warn border-warn-line",
  danger: "bg-danger-soft text-danger border-danger-line",
  info: "bg-info-soft text-info border-info-line",
};

const DOT_TONES: Record<Tone, string> = {
  neutral: "bg-fg-subtle",
  accent: "bg-accent",
  success: "bg-success",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: ComponentProps<"span"> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5",
        "text-[11px] font-medium leading-5 whitespace-nowrap",
        TONES[tone],
        className
      )}
      {...props}
    />
  );
}

/**
 * A status badge whose dot can pulse while work is genuinely in flight. The
 * pulse is suppressed under `prefers-reduced-motion` by the global rule in
 * globals.css, so it degrades to a solid dot rather than disappearing.
 */
export function StatusBadge({
  tone,
  pulse,
  children,
  className,
}: {
  tone: Tone;
  pulse?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Badge tone={tone} className={className}>
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full shrink-0",
          DOT_TONES[tone],
          pulse && "animate-pulse"
        )}
      />
      {children}
    </Badge>
  );
}

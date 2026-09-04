import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";
import type { Tone } from "./Badge";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      aria-hidden
      className={cn("bg-surface-sunken rounded-md animate-pulse", className)}
      {...props}
    />
  );
}

/** A few stacked bars standing in for a list while it loads. */
export function SkeletonList({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("animate-spin size-4", className)}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
    >
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path
        d="M14.5 8A6.5 6.5 0 0 0 8 1.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Empty states say *why* something is empty and what to do next. "Never
 * fabricate" (P§6) has a UI corollary: an honest, specific nothing beats a
 * decorative placeholder that implies data is coming.
 */
export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center gap-2 px-6 py-10",
        className
      )}
    >
      {icon && <div className="text-fg-subtle mb-1">{icon}</div>}
      <p className="text-sm font-medium text-fg">{title}</p>
      {description && (
        <p className="text-xs text-fg-muted max-w-sm leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

const ALERT_TONES: Record<Tone, string> = {
  neutral: "bg-surface-sunken border-line text-fg-muted",
  accent: "bg-accent-soft border-accent-line text-fg",
  success: "bg-success-soft border-success-line text-fg",
  warn: "bg-warn-soft border-warn-line text-fg",
  danger: "bg-danger-soft border-danger-line text-fg",
  info: "bg-info-soft border-info-line text-fg",
};

const ALERT_ICON_TONES: Record<Tone, string> = {
  neutral: "text-fg-subtle",
  accent: "text-accent",
  success: "text-success",
  warn: "text-warn",
  danger: "text-danger",
  info: "text-info",
};

export function Alert({
  tone = "danger",
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex gap-2.5 rounded-lg border px-3.5 py-2.5 text-xs leading-relaxed",
        ALERT_TONES[tone],
        className
      )}
    >
      <svg
        viewBox="0 0 16 16"
        className={cn("size-4 shrink-0 mt-px", ALERT_ICON_TONES[tone])}
        fill="currentColor"
        aria-hidden
      >
        <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM7.25 4.5h1.5v5h-1.5v-5Zm0 6.25h1.5v1.5h-1.5v-1.5Z" />
      </svg>
      <div className="min-w-0">
        {title && <p className="font-medium text-fg">{title}</p>}
        {children}
      </div>
    </div>
  );
}

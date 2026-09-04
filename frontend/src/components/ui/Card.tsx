import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

/**
 * `tone` rather than passing `border-danger-line` through `className`: two
 * border-colour utilities on one element are resolved by their order in the
 * generated stylesheet, not by the order they appear in the class attribute,
 * so an override passed in from outside silently loses. Making it a prop keeps
 * exactly one border utility on the element.
 */
export function Card({
  className,
  tone = "default",
  ...props
}: ComponentProps<"section"> & { tone?: "default" | "danger" }) {
  return (
    <section
      className={cn(
        "bg-surface border rounded-xl shadow-[var(--shadow-card)]",
        tone === "danger" ? "border-danger-line" : "border-line",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 px-5 pt-4 pb-3",
        className
      )}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-fg tracking-tight">{title}</h2>
        {description && (
          <p className="text-xs text-fg-muted mt-1 leading-relaxed">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}

/** A horizontal rule that lines up with card padding. */
export function CardDivider() {
  return <div className="h-px bg-line" />;
}

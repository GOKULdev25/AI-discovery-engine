"use client";

import { useId } from "react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

// Deliberately does NOT set `focus:outline-none`: killing the outline in favour
// of a 25%-opacity ring left keyboard users with a barely-visible focus state.
// The border/ring is the affordance for pointer focus; the global
// `:focus-visible` outline (globals.css) still fires for keyboard focus on top.
const CONTROL =
  "w-full bg-surface text-fg border border-line-strong rounded-lg " +
  "px-3 text-sm transition-colors " +
  "hover:border-fg-subtle " +
  "focus:border-accent focus:ring-2 focus:ring-accent/30 " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

/**
 * Every control gets a real `<label htmlFor>`. The previous UI had none at all,
 * so screen readers announced the inputs as unlabelled and clicking helper text
 * did nothing.
 */
export function Field({
  label,
  hint,
  error,
  children,
  className,
  labelHidden,
}: {
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  children: (props: { id: string; "aria-describedby"?: string }) => ReactNode;
  className?: string;
  labelHidden?: boolean;
}) {
  const id = useId();
  const hintId = hint || error ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label
        htmlFor={id}
        className={cn(
          "text-xs font-medium text-fg-muted",
          labelHidden && "sr-only"
        )}
      >
        {label}
      </label>
      {children({ id, "aria-describedby": hintId })}
      {(hint || error) && (
        <p
          id={hintId}
          className={cn("text-xs", error ? "text-danger" : "text-fg-subtle")}
        >
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(CONTROL, "h-9.5", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(CONTROL, "py-2.5 leading-relaxed resize-y", className)}
      {...props}
    />
  );
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(CONTROL, "h-9.5 pr-8 cursor-pointer appearance-none", className)}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%238a92a3' stroke-width='1.5'%3E%3Cpath d='M4 6l4 4 4-4'/%3E%3C/svg%3E\")",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 0.6rem center",
        backgroundSize: "1rem",
      }}
      {...props}
    />
  );
}

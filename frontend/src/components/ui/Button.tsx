import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-fg hover:bg-accent-hover border border-transparent shadow-xs",
  secondary:
    "bg-surface text-fg border border-line-strong hover:bg-surface-hover",
  ghost: "bg-transparent text-fg-muted border border-transparent hover:bg-surface-hover hover:text-fg",
  // `text-danger-fg`, not `text-white`: in dark mode the danger fill is a light
  // red, where white text measured 2.85:1.
  danger: "bg-danger text-danger-fg border border-transparent hover:opacity-90",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-md",
  md: "h-9.5 px-4 text-sm gap-2 rounded-lg",
};

const BASE =
  "inline-flex items-center justify-center font-medium whitespace-nowrap " +
  "transition-colors duration-150 select-none " +
  "disabled:opacity-45 disabled:pointer-events-none";

function classesFor(variant: Variant, size: Size, className?: string) {
  return cn(BASE, VARIANTS[variant], SIZES[size], className);
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ComponentProps<"button"> & { variant?: Variant; size?: Size }) {
  return <button className={classesFor(variant, size, className)} {...props} />;
}

/** Same visual language as `Button`, for real navigation (keeps ⌘-click working). */
export function ButtonLink({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; size?: Size }) {
  return <Link className={classesFor(variant, size, className)} {...props} />;
}

/**
 * A plain `<a>` in button clothing — used for the Excel export, where the point
 * is to let the browser perform a real download from the API's own URL rather
 * than fetch a blob and synthesise a click.
 */
export function ButtonAnchor({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ComponentProps<"a"> & { variant?: Variant; size?: Size }) {
  return <a className={classesFor(variant, size, className)} {...props} />;
}

export function IconButton({
  label,
  children,
  className,
  ...props
}: ComponentProps<"button"> & { label: string; children: ReactNode }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cn(
        BASE,
        VARIANTS.ghost,
        "h-8 w-8 rounded-md p-0",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

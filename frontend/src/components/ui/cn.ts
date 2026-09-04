/**
 * Minimal class-name joiner. Deliberately not `clsx`/`tailwind-merge` — the
 * repo runs a blocked/paid-dependency scan (EV-INV-11) and a $0 constraint
 * (A§1), so the bar for adding any package at all is "this cannot reasonably
 * be six lines". This can.
 */
export type ClassValue = string | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}

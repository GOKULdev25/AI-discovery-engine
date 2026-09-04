import Link from "next/link";
import type { ReactNode } from "react";
import { QuotaBudget } from "./QuotaBudget";
import { ThemeToggle } from "./ThemeToggle";

/**
 * The one persistent chrome in the app. Previously each of the three screens
 * hand-rolled its own back-link and there was no global surface at all, so the
 * AI budget and the theme control had nowhere consistent to live.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-100
                   focus:rounded-lg focus:bg-surface-raised focus:px-3 focus:py-2
                   focus:text-sm focus:shadow-[var(--shadow-pop)]"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-5 sm:px-6">
          <Link
            href="/"
            className="group flex items-center gap-2.5 rounded-md -m-1 p-1 min-w-0"
          >
            <Mark />
            {/* Hidden on the narrowest screens: truncated to "Discove…" it read
                as a bug, and the mark alone is unambiguous next to it. */}
            <span className="hidden truncate text-sm font-semibold tracking-tight text-fg sm:inline">
              Discovery Engine
            </span>
          </Link>

          <div className="ml-auto flex items-center gap-2.5">
            <QuotaBudget />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main id="main" className="flex-1">
        {children}
      </main>

      <footer className="border-t border-line py-5">
        <div className="mx-auto w-full max-w-6xl px-5 sm:px-6">
          <p className="text-[11px] leading-relaxed text-fg-subtle">
            Every figure here is traceable to a source document. Nothing is inferred
            beyond what was extracted.
          </p>
        </div>
      </footer>
    </>
  );
}

function Mark() {
  return (
    <span
      aria-hidden
      className="grid size-7 shrink-0 place-items-center rounded-lg bg-accent text-accent-fg
                 shadow-[var(--shadow-card)] transition-transform group-hover:scale-105"
    >
      <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.75">
        <circle cx="7" cy="7" r="4.25" />
        <path d="M10.2 10.2 13.5 13.5" strokeLinecap="round" />
      </svg>
    </span>
  );
}

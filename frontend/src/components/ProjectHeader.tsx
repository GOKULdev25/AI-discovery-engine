"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, exportUrl } from "@/lib/api";
import { ButtonAnchor, ButtonLink } from "./ui/Button";
import { Badge } from "./ui/Badge";
import { Skeleton } from "./ui/Feedback";
import { cn } from "./ui/cn";

const TABS = [
  { slug: "", label: "Extract" },
  { slug: "documents", label: "Documents" },
  { slug: "dashboard", label: "Dashboard" },
  { slug: "chat", label: "Ask" },
] as const;

/**
 * One header for every project screen — the back link, identity, the actions
 * that were previously unreachable (Excel export, settings), and the tab bar.
 *
 * Replaces three separately hand-rolled back-links that each looked and behaved
 * a little differently.
 */
export function ProjectHeader({ projectId }: { projectId: string }) {
  const pathname = usePathname();
  const base = `/projects/${projectId}`;

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: async () => {
      const { data, error } = await api.GET("/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      });
      if (error) throw error;
      return data;
    },
  });

  const project = projectQuery.data;
  const activeSlug = pathname.startsWith(base)
    ? pathname.slice(base.length).replace(/^\//, "").split("/")[0]
    : "";

  return (
    <div className="border-b border-line bg-surface">
      <div className="mx-auto w-full max-w-6xl px-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 pt-5">
          <div className="min-w-0">
            <Link
              href="/"
              className="inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg transition-colors"
            >
              <svg viewBox="0 0 16 16" className="size-3" fill="currentColor" aria-hidden>
                <path d="M10.3 3.3a.75.75 0 0 1 0 1.06L6.66 8l3.64 3.64a.75.75 0 1 1-1.06 1.06L5.07 8.53a.75.75 0 0 1 0-1.06L9.24 3.3a.75.75 0 0 1 1.06 0Z" />
              </svg>
              All projects
            </Link>

            {projectQuery.isLoading ? (
              <Skeleton className="mt-1.5 h-7 w-56" />
            ) : (
              <h1 className="mt-0.5 truncate text-xl font-semibold tracking-tight text-fg sm:text-2xl">
                {project?.name ?? projectId}
              </h1>
            )}

            {project && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <Badge tone={project.session_mode === "operator_session" ? "info" : "neutral"}>
                  {project.session_mode === "operator_session"
                    ? "Operator session"
                    : "Logged out"}
                </Badge>
                {(project.locales ?? []).length > 0 && (
                  <span className="text-xs text-fg-subtle">
                    {(project.locales ?? []).join(" · ").toUpperCase()}
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <ButtonAnchor
              href={exportUrl(projectId)}
              size="sm"
              variant="secondary"
              // A same-origin-policy-independent file download straight from the API.
              download
            >
              <svg viewBox="0 0 16 16" className="size-3.5" fill="currentColor" aria-hidden>
                <path d="M8 1.5a.75.75 0 0 1 .75.75v6.19l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 0 1 1.06-1.06l2.22 2.22V2.25A.75.75 0 0 1 8 1.5ZM2.75 11a.75.75 0 0 1 .75.75v1a.25.25 0 0 0 .25.25h8.5a.25.25 0 0 0 .25-.25v-1a.75.75 0 0 1 1.5 0v1A1.75 1.75 0 0 1 12.25 14.5h-8.5A1.75 1.75 0 0 1 2 12.75v-1a.75.75 0 0 1 .75-.75Z" />
              </svg>
              Export Excel
            </ButtonAnchor>
            <ButtonLink
              href={`${base}/settings`}
              size="sm"
              variant={activeSlug === "settings" ? "primary" : "ghost"}
              aria-label="Project settings"
            >
              <svg viewBox="0 0 16 16" className="size-3.5" fill="currentColor" aria-hidden>
                <path d="M8 10.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Zm5.9-2.5c0-.35-.03-.68-.09-1l1.28-.99-1.3-2.26-1.5.6a5.2 5.2 0 0 0-1.74-1l-.23-1.6H7.68l-.23 1.6c-.64.22-1.23.56-1.74 1l-1.5-.6-1.3 2.26.99 1a5.4 5.4 0 0 0 0 2l-1 .99 1.3 2.26 1.51-.6c.51.44 1.1.78 1.74 1l.23 1.6h2.64l.23-1.6a5.2 5.2 0 0 0 1.74-1l1.5.6 1.3-2.26-1.27-.99c.06-.32.09-.65.09-1Z" />
              </svg>
              <span className="sr-only sm:not-sr-only">Settings</span>
            </ButtonLink>
          </div>
        </div>

        <nav aria-label="Project sections" className="-mb-px mt-4 flex gap-1 overflow-x-auto">
          {TABS.map((tab) => {
            const href = tab.slug ? `${base}/${tab.slug}` : base;
            const active = activeSlug === tab.slug;
            return (
              <Link
                key={tab.slug}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative whitespace-nowrap px-3 py-2.5 text-sm font-medium transition-colors",
                  "border-b-2",
                  active
                    ? "border-accent text-fg"
                    : "border-transparent text-fg-muted hover:text-fg"
                )}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}

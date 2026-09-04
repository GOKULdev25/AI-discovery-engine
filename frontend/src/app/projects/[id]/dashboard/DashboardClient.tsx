"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { ProjectHeader } from "@/components/ProjectHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Select } from "@/components/ui/Field";
import { Badge } from "@/components/ui/Badge";
import { Alert, Skeleton, SkeletonList } from "@/components/ui/Feedback";
import { cn } from "@/components/ui/cn";
import { BarList, StatTile } from "@/components/charts/chrome";
import { OverallPanel } from "@/components/charts/OverallPanel";
import { SourcePanel, type SourceBlock } from "@/components/charts/SourcePanel";
import { ChatPane } from "@/components/charts/ChatPane";
import { profileFor, useSourceProfiles } from "@/lib/sourceProfiles";
import {
  failureLabel,
  formatDate,
  formatRelative,
  sourceLabel,
} from "@/lib/labels";

type Meta = {
  document_count: number;
  sources: string[];
  mixed_source: boolean;
  captured_from: string | null;
  captured_to: string | null;
};

type BySourceResponse = { meta: Meta; sources: SourceBlock[] };

const OVERALL = "__overall__";

export function DashboardClient({ projectId }: { projectId: string }) {
  const [batchId, setBatchId] = useState("");
  const [view, setView] = useState<string>(OVERALL);

  const profilesQuery = useSourceProfiles();

  const batchesQuery = useQuery({
    queryKey: ["batches", projectId],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/batches",
        { params: { path: { project_id: projectId } } }
      );
      if (error) throw error;
      return data;
    },
  });

  const bySourceQuery = useQuery({
    queryKey: ["analytics", "by-source", projectId, batchId],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/analytics/by-source",
        {
          params: {
            path: { project_id: projectId },
            query: batchId ? { batch_id: batchId } : {},
          },
        }
      );
      if (error) throw error;
      return data as BySourceResponse;
    },
  });

  const failuresQuery = useQuery({
    queryKey: ["analytics", "failures", projectId, batchId],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/analytics/failures",
        {
          params: {
            path: { project_id: projectId },
            query: batchId ? { batch_id: batchId } : {},
          },
        }
      );
      if (error) throw error;
      return data as { total_links: number; data: { failure_code: string; count: number }[] };
    },
  });

  const termsQuery = useQuery({
    queryKey: ["analytics", "themes", projectId, batchId],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/analytics/themes",
        {
          params: {
            path: { project_id: projectId },
            query: batchId ? { batch_id: batchId } : {},
          },
        }
      );
      if (error) throw error;
      return data as { meta: Meta; data: { term: string; freq: number }[] };
    },
  });

  const meta = bySourceQuery.data?.meta;
  const blocks = useMemo(
    () => bySourceQuery.data?.sources ?? [],
    [bySourceQuery.data]
  );
  const activeBlock =
    view === OVERALL ? null : blocks.find((b) => b.source === view) ?? null;

  const failures = failuresQuery.data;
  const failedCount =
    failures?.data.reduce((sum, f) => sum + f.count, 0) ?? 0;

  // Every headline number follows the active view. The KPI row previously
  // reported the whole project regardless, so selecting one source left a
  // "369 documents" tile above a panel counting 349.
  const scopedCount = activeBlock?.doc_count ?? meta?.document_count ?? 0;
  const scopedFrom = activeBlock?.captured_from ?? meta?.captured_from ?? null;
  const scopedTo = activeBlock?.captured_to ?? meta?.captured_to ?? null;
  const activeProfile = activeBlock
    ? profileFor(profilesQuery.data?.profiles, activeBlock.source)
    : null;

  const scopeLabel = `Answering from ${
    activeBlock ? activeBlock.label : "all sources"
  } across ${batchId ? "this run" : "the whole project"}`;

  return (
    <>
      <ProjectHeader projectId={projectId} />

      <main id="main" className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        {/* ------------------------------------------------- filter row */}
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Field label="Filter to a run" className="w-full sm:max-w-xs">
            {(props) => (
              <Select
                {...props}
                value={batchId}
                onChange={(e) => setBatchId(e.target.value)}
              >
                <option value="">All runs</option>
                {batchesQuery.data?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {formatRelative(b.created_at)} · {b.link_count} links
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <div className="min-w-0 flex-1">
            <p className="mb-1.5 text-xs font-medium text-fg-muted">View</p>
            {/* Scrolls within its own track rather than widening the page.
                Measured: at 414px these buttons pushed the document to
                452px, so the whole dashboard scrolled sideways. `min-w-0`
                on the parent is what actually lets a flex child shrink
                below its content width. */}
            <div
              role="tablist"
              aria-label="Chart scope"
              className="flex gap-1 overflow-x-auto rounded-lg border border-line bg-surface p-1 [scrollbar-width:thin]"
            >
              <ViewTab
                active={view === OVERALL}
                onClick={() => setView(OVERALL)}
              >
                All sources
              </ViewTab>
              {blocks.map((b) => (
                <ViewTab
                  key={b.source}
                  active={view === b.source}
                  onClick={() => setView(b.source)}
                >
                  {b.label}
                  <span
                    className={cn(
                      "ml-1.5",
                      view === b.source ? "opacity-70" : "text-fg-subtle"
                    )}
                  >
                    {b.doc_count.toLocaleString()}
                  </span>
                </ViewTab>
              ))}
            </div>
          </div>
        </div>

        {/* ------------------------------------------------- denominator
            Scoped to the active view. Showing the project-wide count while
            a single source's panel is on screen made the caption disagree
            with the charts underneath it. */}
        <div className="mb-4 text-xs text-fg-muted">
          {meta ? (
            scopedCount === 0 ? (
              "No documents captured yet."
            ) : (
              <>
                Everything below describes{" "}
                <strong className="tnum font-semibold text-fg">
                  {scopedCount.toLocaleString()}
                </strong>{" "}
                documents from{" "}
                {activeBlock
                  ? activeBlock.label
                  : meta.sources.map((s) => sourceLabel(s)).join(", ")}
                {scopedFrom && scopedTo && (
                  <>
                    , captured {formatDate(scopedFrom)} – {formatDate(scopedTo)}
                  </>
                )}
                .
              </>
            )
          ) : (
            <Skeleton className="h-4 w-96" />
          )}
        </div>

        {/* ------------------------------------------------- KPI row */}
        <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          <StatTile
            label="Documents"
            value={
              meta ? scopedCount.toLocaleString() : <Skeleton className="h-7 w-16" />
            }
            hint={activeBlock ? activeBlock.label : "all sources"}
          />

          {activeBlock ? (
            <>
              <StatTile
                label="Type"
                value={
                  activeBlock.doc_types.length === 1
                    ? activeBlock.doc_types[0].name.replace(/_/g, " ")
                    : activeBlock.doc_types.length
                }
                hint={
                  activeBlock.doc_types.length === 1
                    ? "one document type"
                    : activeBlock.doc_types.map((t) => t.name).join(", ")
                }
              />
              <StatTile
                label={activeBlock.engagement?.label ?? "Engagement"}
                value={
                  activeBlock.engagement
                    ? activeBlock.engagement.total.toLocaleString()
                    : "—"
                }
                hint={
                  activeBlock.engagement
                    ? `max ${activeBlock.engagement.max.toLocaleString()}`
                    : "not captured for this source"
                }
              />
              <StatTile
                label={activeProfile?.rating?.label ?? "Rating"}
                value={
                  activeProfile?.rating
                    ? activeBlock.rating_coverage.toLocaleString()
                    : "—"
                }
                hint={
                  activeProfile?.rating
                    ? `of ${activeBlock.doc_count.toLocaleString()} carry one`
                    : "this source has no ratings"
                }
              />
            </>
          ) : (
            <>
              <StatTile
                label="Sources"
                value={meta ? meta.sources.length : <Skeleton className="h-7 w-8" />}
                hint={meta?.sources.map((s) => sourceLabel(s)).join(", ")}
              />
              <StatTile
                label="Links attempted"
                value={
                  failures ? (
                    failures.total_links.toLocaleString()
                  ) : (
                    <Skeleton className="h-7 w-12" />
                  )
                }
              />
              <StatTile
                label="Failed links"
                tone={failedCount > 0 ? "danger" : "default"}
                value={
                  failures ? failedCount.toLocaleString() : <Skeleton className="h-7 w-12" />
                }
                hint={failedCount > 0 ? "see run health below" : "none"}
              />
            </>
          )}
        </div>

        {/* ------------------------------------------------- main grid */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(20rem,1fr)] 2xl:grid-cols-[minmax(0,2.4fr)_minmax(24rem,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            {bySourceQuery.isPending && <SkeletonList rows={3} />}
            {bySourceQuery.isError && (
              <Alert tone="danger" title="Could not load the charts">
                The analytics endpoint returned an error. The extraction data
                itself is unaffected.
              </Alert>
            )}

            {meta && view === OVERALL && (
              <OverallPanel
                blocks={blocks}
                mixedSource={meta.mixed_source}
                capturedFrom={meta.captured_from}
                capturedTo={meta.captured_to}
                documentCount={meta.document_count}
              />
            )}

            {activeBlock && (
              <SourcePanel
                block={activeBlock}
                profile={profileFor(profilesQuery.data?.profiles, activeBlock.source)}
              />
            )}

            {/* Frequent words — named for what it is. This is a raw word
                count with a stopword list, not a topic model, and calling
                it "themes" oversold it. */}
            {view === OVERALL && (termsQuery.data?.data.length ?? 0) > 0 && (
              <Card>
                <CardHeader
                  title="Frequent words"
                  description="Raw word counts with common filler removed — not a topic model"
                />
                <CardBody>
                  <BarList
                    items={
                      termsQuery.data?.data.slice(0, 12).map((t) => ({
                        name: t.term,
                        doc_count: t.freq,
                      })) ?? []
                    }
                    total={termsQuery.data?.data[0]?.freq ?? 1}
                  />
                </CardBody>
              </Card>
            )}

            {/* Run health — the pipeline telemetry that used to lead the
                page. Still here, because "fail loudly" (P§6) means a failed
                link must stay visible; just no longer the headline. */}
            <Card tone={failedCount > 0 ? "danger" : "default"}>
              <CardHeader
                title="Run health"
                description={
                  failures
                    ? `${failures.total_links.toLocaleString()} links attempted${
                        failedCount > 0 ? ` · ${failedCount.toLocaleString()} failed` : " · none failed"
                      }`
                    : "Loading…"
                }
              />
              <CardBody>
                {failedCount === 0 ? (
                  <p className="text-xs text-fg-subtle">
                    Every link resolved. Nothing was dropped silently.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {failures?.data.map((f) => (
                      <li
                        key={f.failure_code}
                        className="flex items-center gap-2 text-xs"
                      >
                        <Badge tone="danger">{failureLabel(f.failure_code)}</Badge>
                        <code className="text-[10px] text-fg-subtle">
                          {f.failure_code}
                        </code>
                        <span className="tnum ml-auto font-medium text-fg">
                          {f.count.toLocaleString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
          </div>

          {/* Chat on the same screen, scoped to the same filter. */}
          <div className="min-w-0">
            <div className="lg:sticky lg:top-4">
              <ChatPane
                projectId={projectId}
                batchId={batchId}
                source={view === OVERALL ? "" : view}
                scopeLabel={scopeLabel}
                searchableCount={null}
                droppedCount={null}
              />
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

function ViewTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "shrink-0 cursor-pointer whitespace-nowrap rounded-md px-3 py-1.5",
        "text-xs font-medium transition-colors duration-150",
        active
          ? "bg-accent text-accent-fg"
          : "text-fg-muted hover:bg-surface-hover hover:text-fg"
      )}
    >
      {children}
    </button>
  );
}

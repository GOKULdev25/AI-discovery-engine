"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, sseUrl } from "@/lib/api";
import { ProjectHeader } from "@/components/ProjectHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Textarea } from "@/components/ui/Field";
import { Alert, EmptyState, SkeletonList, Spinner } from "@/components/ui/Feedback";
import { StatusBadge, type Tone } from "@/components/ui/Badge";
import { SegmentedProgress } from "@/components/ui/Progress";
import { cn } from "@/components/ui/cn";
import {
  FAILURE_HINTS,
  failureLabel,
  formatRelative,
  sourceLabel,
} from "@/lib/labels";

type LinkRow = {
  id: string;
  url: string;
  connector_id: string | null;
  status: string;
  failure_code: string | null;
  retryable: number | boolean | null;
  doc_count: number | null;
};

/** SSE only ever carries deltas; these overlay whatever the API last returned. */
type LivePatch = Partial<Pick<LinkRow, "status" | "failure_code" | "retryable" | "doc_count">>;

const STATUS_TONE: Record<string, Tone> = {
  done: "success",
  failed: "danger",
  running: "warn",
  pending: "neutral",
};

export function ProjectDetailClient({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [urlsText, setUrlsText] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [liveBatchId, setLiveBatchId] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, LivePatch>>({});
  const [dragging, setDragging] = useState(false);

  /* ---------------------------------------------------------------- queries */

  const batchesQuery = useQuery({
    queryKey: ["batches", projectId],
    queryFn: async () => {
      const { data, error } = await api.GET("/projects/{project_id}/batches", {
        params: { path: { project_id: projectId } },
      });
      if (error) throw error;
      return data;
    },
  });

  const batches = useMemo(() => batchesQuery.data ?? [], [batchesQuery.data]);

  // Default to the newest run, so arriving at (or reloading) this page always
  // shows the last thing that happened rather than an empty form — and if that
  // run is still in flight, re-attach the SSE stream to it. Without this a
  // reload mid-batch would show a correct-but-frozen snapshot that never
  // advanced, which is arguably worse than showing nothing.
  useEffect(() => {
    if (selectedBatchId || batches.length === 0) return;
    const newest = batches[0];
    setSelectedBatchId(newest.id);
    if (newest.status === "running" || newest.status === "pending") {
      setLiveBatchId(newest.id);
    }
  }, [batches, selectedBatchId]);

  const linksQuery = useQuery({
    queryKey: ["batch-links", projectId, selectedBatchId],
    enabled: Boolean(selectedBatchId),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/batches/{batch_id}/links",
        {
          params: {
            path: { project_id: projectId, batch_id: selectedBatchId as string },
          },
        }
      );
      if (error) throw error;
      return data as unknown as LinkRow[];
    },
  });

  /* -------------------------------------------------------------- mutations */

  const submitBatch = useMutation({
    mutationFn: async (urls: string[]) => {
      const { data, error } = await api.POST("/projects/{project_id}/batches", {
        params: { path: { project_id: projectId } },
        body: { urls },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (data) => {
      setUrlsText("");
      setLive({});
      setSelectedBatchId(data.batch_id);
      setLiveBatchId(data.batch_id);
      queryClient.invalidateQueries({ queryKey: ["batches", projectId] });
    },
  });

  const retryBatch = useMutation({
    mutationFn: async (batchId: string) => {
      const { data, error } = await api.POST(
        "/projects/{project_id}/batches/{batch_id}/retry",
        { params: { path: { project_id: projectId, batch_id: batchId } } }
      );
      if (error) throw error;
      return data;
    },
    onSuccess: (_data, batchId) => setLiveBatchId(batchId),
  });

  /* -------------------------------------------------------------------- SSE */

  useEffect(() => {
    if (!liveBatchId) return;

    const es = new EventSource(sseUrl(projectId, liveBatchId));

    es.addEventListener("link.status", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setLive((prev) => ({
        ...prev,
        [d.link_id]: {
          ...prev[d.link_id],
          status: d.status,
          failure_code: d.failure_code ?? null,
          retryable: d.retryable ?? null,
        },
      }));
    });

    es.addEventListener("link.docs", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setLive((prev) => ({
        ...prev,
        [d.link_id]: { ...prev[d.link_id], doc_count: d.doc_count },
      }));
    });

    es.addEventListener("batch.done", () => {
      es.close();
      setLiveBatchId(null);
      // Re-read from the API so the durable rows (not the in-memory overlay)
      // become the source of truth the moment the run finishes.
      queryClient.invalidateQueries({ queryKey: ["batches", projectId] });
      queryClient.invalidateQueries({ queryKey: ["batch-links", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    });

    es.onerror = () => {
      // The browser's built-in EventSource retries automatically, sending
      // Last-Event-ID so the backend replays anything missed (EV-P0-08) —
      // nothing to do here but let it.
    };

    return () => es.close();
  }, [projectId, liveBatchId, queryClient]);

  /* ---------------------------------------------------------------- derived */

  const rows: LinkRow[] = useMemo(() => {
    const base = linksQuery.data ?? [];
    if (Object.keys(live).length === 0) return base;
    return base.map((r) => (live[r.id] ? { ...r, ...live[r.id] } : r));
  }, [linksQuery.data, live]);

  const tally = useMemo(() => {
    const t = { done: 0, failed: 0, running: 0, pending: 0 };
    for (const r of rows) {
      if (r.status in t) t[r.status as keyof typeof t] += 1;
      else t.pending += 1;
    }
    return t;
  }, [rows]);

  const isLive = liveBatchId !== null && liveBatchId === selectedBatchId;
  const hasRetryable = rows.some((r) => r.status === "failed" && Boolean(r.retryable));
  const totalDocs = rows.reduce((sum, r) => sum + (r.doc_count ?? 0), 0);

  const parsedLinks = useMemo(
    () => urlsText.split("\n").map((l) => l.trim()).filter(Boolean),
    [urlsText]
  );
  const suspectCount = parsedLinks.filter((l) => !looksLikeUrl(l)).length;

  const readFile = useCallback((file: File) => {
    file.text().then((text) =>
      setUrlsText((prev) => (prev.trim() ? `${prev.trim()}\n${text.trim()}` : text.trim()))
    );
  }, []);

  return (
    <>
      <ProjectHeader projectId={projectId} />

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 py-8 sm:px-6">
        {/* ------------------------------------------------------ paste box */}
        <Card>
          <CardHeader
            title="Extract"
            description="One link per line — YouTube videos, Reddit threads, App Store / Play Store listings, Flipkart or Amazon products. Anything else falls back to an LLM read of the page."
          />
          <CardBody>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) readFile(file);
              }}
              className={cn("rounded-lg transition-shadow", dragging && "ring-2 ring-accent")}
            >
              <Field label="Links to extract" labelHidden>
                {(fieldProps) => (
                  <Textarea
                    {...fieldProps}
                    rows={6}
                    className="font-mono text-[13px]"
                    placeholder={"https://www.youtube.com/watch?v=…\nhttps://www.reddit.com/r/…\nhttps://play.google.com/store/apps/details?id=…"}
                    value={urlsText}
                    onChange={(e) => setUrlsText(e.target.value)}
                  />
                )}
              </Field>
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-fg-muted" aria-live="polite">
                <span className="tnum font-medium text-fg">{parsedLinks.length}</span>{" "}
                {parsedLinks.length === 1 ? "link" : "links"}
                {suspectCount > 0 && (
                  <span className="text-warn">
                    {" "}
                    · {suspectCount} {suspectCount === 1 ? "doesn't look like a URL" : "don't look like URLs"}
                  </span>
                )}
                <span className="text-fg-subtle"> · or drop a .txt file</span>
              </p>
              <Button
                variant="primary"
                disabled={submitBatch.isPending || parsedLinks.length === 0}
                onClick={() => submitBatch.mutate(parsedLinks)}
              >
                {submitBatch.isPending ? (
                  <>
                    <Spinner /> Submitting…
                  </>
                ) : (
                  <>Extract {parsedLinks.length > 0 && `${parsedLinks.length} `}→</>
                )}
              </Button>
            </div>

            {submitBatch.isError && (
              <Alert tone="danger" title="Couldn't submit the batch" className="mt-3">
                The backend rejected the request or is unreachable.
              </Alert>
            )}
          </CardBody>
        </Card>

        {/* ------------------------------------------------- runs + link table */}
        <div className="grid gap-6 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] lg:items-start">
          <Card>
            <CardHeader
              title="Runs"
              description={batches.length > 0 ? undefined : "Batches appear here as you submit them."}
            />
            <CardBody className="px-2 pb-2">
              {batchesQuery.isLoading && <SkeletonList rows={2} className="px-3 pb-2" />}
              {batches.length === 0 && !batchesQuery.isLoading && (
                <p className="px-3 pb-3 text-xs text-fg-subtle">No runs yet.</p>
              )}
              <ul className="flex flex-col gap-0.5">
                {batches.map((b) => {
                  const active = b.id === selectedBatchId;
                  const failed = b.counts?.failed ?? 0;
                  const done = b.counts?.done ?? 0;
                  return (
                    <li key={b.id}>
                      <button
                        onClick={() => {
                          setSelectedBatchId(b.id);
                          setLive({});
                        }}
                        aria-current={active ? "true" : undefined}
                        className={cn(
                          "w-full rounded-lg px-3 py-2.5 text-left transition-colors",
                          active ? "bg-accent-soft" : "hover:bg-surface-hover"
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={cn(
                              "text-xs font-medium",
                              active ? "text-accent" : "text-fg"
                            )}
                          >
                            {formatRelative(b.created_at)}
                          </span>
                          {b.id === liveBatchId ? (
                            <StatusBadge tone="warn" pulse>
                              Running
                            </StatusBadge>
                          ) : failed > 0 ? (
                            <StatusBadge tone="danger">{failed} failed</StatusBadge>
                          ) : (
                            <StatusBadge tone="success">Done</StatusBadge>
                          )}
                        </div>
                        <p className="tnum mt-1 text-[11px] text-fg-subtle">
                          {b.link_count} {b.link_count === 1 ? "link" : "links"}
                          {done > 0 && ` · ${done} ok`}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </CardBody>
          </Card>

          <Card className="min-w-0">
            <CardHeader
              title={isLive ? "Extracting…" : "Run detail"}
              description={
                selectedBatchId
                  ? `${rows.length} ${rows.length === 1 ? "link" : "links"} · ${totalDocs.toLocaleString()} documents collected`
                  : "Select a run to see every link and its outcome."
              }
              actions={
                hasRetryable && !isLive ? (
                  <Button
                    size="sm"
                    onClick={() => selectedBatchId && retryBatch.mutate(selectedBatchId)}
                    disabled={retryBatch.isPending}
                  >
                    Retry failed
                  </Button>
                ) : undefined
              }
            />

            {rows.length > 0 && (
              <div className="px-5 pb-4">
                <SegmentedProgress
                  total={rows.length}
                  label="Batch progress"
                  segments={[
                    { value: tally.done, color: "var(--success)", label: "done" },
                    { value: tally.failed, color: "var(--danger)", label: "failed" },
                    { value: tally.running, color: "var(--warn)", label: "running" },
                  ]}
                />
                <p className="tnum mt-2 text-xs text-fg-muted" aria-live="polite">
                  {tally.done} done
                  {tally.failed > 0 && <span className="text-danger"> · {tally.failed} failed</span>}
                  {tally.running > 0 && <span className="text-warn"> · {tally.running} running</span>}
                  {tally.pending > 0 && <span className="text-fg-subtle"> · {tally.pending} queued</span>}
                </p>
              </div>
            )}

            <CardBody className="px-0 pb-0">
              {linksQuery.isLoading && <SkeletonList rows={3} className="px-5 pb-5" />}

              {!selectedBatchId && !batchesQuery.isLoading && (
                <EmptyState
                  title="Nothing extracted yet"
                  description="Paste some links above and hit Extract. Progress appears here live, and stays here afterwards."
                />
              )}

              {selectedBatchId && rows.length > 0 && (
                <div className="overflow-x-auto">
                  {/* Below `sm` the Source/Status columns collapse into the link
                      cell, so the table fits without horizontal scrolling and
                      status — the thing you actually came to read — stays on
                      screen. From `sm` up it is a normal wide table. */}
                  <table className="w-full text-sm sm:min-w-[40rem]">
                    <thead>
                      <tr className="border-y border-line text-left text-[11px] uppercase tracking-wide text-fg-subtle">
                        {/* `w-full` here + `max-w-0` on the cell is what lets the
                            URL column absorb all remaining width and truncate,
                            instead of collapsing to its shortest content. */}
                        <th className="w-full px-5 py-2 font-medium">Link</th>
                        <th className="hidden px-3 py-2 font-medium sm:table-cell">Source</th>
                        <th className="hidden px-3 py-2 font-medium sm:table-cell">Status</th>
                        <th className="px-5 py-2 text-right font-medium">Docs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr
                          key={row.id}
                          className="border-b border-line/60 last:border-0 hover:bg-surface-hover"
                        >
                          <td className="max-w-0 px-5 py-2.5">
                            <span className="block truncate font-mono text-xs text-fg-muted" title={row.url}>
                              {row.url}
                            </span>
                            {row.status === "failed" && row.failure_code && (
                              <span className="mt-0.5 block text-[11px] leading-relaxed text-fg-subtle">
                                {FAILURE_HINTS[row.failure_code]}
                              </span>
                            )}
                            <span className="mt-1.5 flex items-center gap-2 sm:hidden">
                              <StatusBadge
                                tone={STATUS_TONE[row.status] ?? "neutral"}
                                pulse={row.status === "running"}
                              >
                                {statusText(row)}
                              </StatusBadge>
                              {row.connector_id && (
                                <span className="text-[11px] text-fg-subtle">
                                  {sourceLabel(row.connector_id)}
                                </span>
                              )}
                            </span>
                          </td>
                          <td className="hidden px-3 py-2.5 text-xs text-fg-muted sm:table-cell">
                            {row.connector_id ? sourceLabel(row.connector_id) : "—"}
                          </td>
                          <td className="hidden px-3 py-2.5 sm:table-cell">
                            <StatusBadge
                              tone={STATUS_TONE[row.status] ?? "neutral"}
                              pulse={row.status === "running"}
                            >
                              {statusText(row)}
                            </StatusBadge>
                          </td>
                          <td className="tnum px-5 py-2.5 text-right text-xs text-fg-muted">
                            {row.doc_count ? row.doc_count.toLocaleString() : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}

/** A failed link reads as its typed reason, never the word "failed" — the
 *  reason is the whole point of the taxonomy (A§8.1, P§8). */
function statusText(row: LinkRow): string {
  if (row.status === "failed") return failureLabel(row.failure_code);
  if (row.status === "done") return "Done";
  if (row.status === "running") return "Running";
  return "Queued";
}

/** A light client-side sanity check, purely to warn before submitting — the
 *  backend's `classify_url` remains the only real authority (A§8.1). */
function looksLikeUrl(value: string): boolean {
  return /^(https?:\/\/|fixture:\/\/)\S+$/i.test(value);
}

"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { ProjectHeader } from "@/components/ProjectHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Field, Input, Select } from "@/components/ui/Field";
import { Alert, EmptyState, SkeletonList, Spinner } from "@/components/ui/Feedback";
import { DocumentCard, type Doc } from "@/components/documents/DocumentCard";
import { profileFor, useSourceProfiles } from "@/lib/sourceProfiles";
import {
  GATE_BAND_LABELS,
  LANE_DESCRIPTIONS,
  formatDate,
  formatRelative,
  laneLabel,
  sourceLabel,
} from "@/lib/labels";

const PAGE_SIZE = 50;

/** The source's own word for its engagement metric, so a like is never
 *  presented as an upvote. Falls back to the raw kind if unlabelled. */
function engagementLabel(doc: Doc): string {
  const kind = doc.engagement_kind ?? "";
  const named: Record<string, string> = {
    likes: "Likes",
    score: "Score",
    helpful: "Found helpful",
    thumbs_up: "Thumbs up",
    vote_sum: "Helpful votes",
  };
  return named[kind] ?? "Engagement";
}

/**
 * The evidence itself — previously unreachable from the UI even though the
 * endpoint has been keyset-paginated and filterable since Phase 4.
 *
 * Keyset, not offset: a batch finishing mid-scroll shifts an OFFSET window and
 * would silently skip or repeat rows. The cursor only ever moves forward past
 * rows already seen (EV-P4-09).
 */
export function DocumentsClient({ projectId }: { projectId: string }) {
  const [source, setSource] = useState("");
  const [gateBand, setGateBand] = useState("");
  const [batchId, setBatchId] = useState("");
  const [search, setSearch] = useState("");
  // The query the server actually sees. Typing re-issues a keyset query, so
  // it is debounced rather than fired on every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [openDoc, setOpenDoc] = useState<Doc | null>(null);

  const profilesQuery = useSourceProfiles();

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

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

  const sourcesQuery = useQuery({
    queryKey: ["analytics", "sources", projectId, ""],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/analytics/sources",
        { params: { path: { project_id: projectId } } }
      );
      if (error) throw error;
      return data;
    },
  });

  const docsQuery = useInfiniteQuery({
    queryKey: ["documents", projectId, source, gateBand, batchId, debouncedSearch],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/projects/{project_id}/documents", {
        params: {
          path: { project_id: projectId },
          query: {
            limit: PAGE_SIZE,
            ...(pageParam ? { cursor: pageParam } : {}),
            ...(source ? { source } : {}),
            ...(gateBand ? { gate_band: gateBand } : {}),
            ...(batchId ? { batch_id: batchId } : {}),
            ...(debouncedSearch ? { q: debouncedSearch } : {}),
          },
        },
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const docs = useMemo(
    () => (docsQuery.data?.pages.flatMap((p) => p.documents) ?? []) as Doc[],
    [docsQuery.data]
  );

  const anyFilter = Boolean(source || gateBand || batchId || debouncedSearch);

  return (
    <>
      <ProjectHeader projectId={projectId} />

      <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-6">
        <Card>
          <div className="flex flex-wrap items-end gap-3 border-b border-line px-5 py-4">
            <Field label="Source" className="w-44">
              {(p) => (
                <Select
                  {...p}
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  className="h-8 text-xs"
                >
                  <option value="">All sources</option>
                  {(sourcesQuery.data?.data ?? []).map((s) => (
                    <option key={s.source} value={s.source}>
                      {sourceLabel(s.source)} ({s.doc_count.toLocaleString()})
                    </option>
                  ))}
                </Select>
              )}
            </Field>

            <Field label="Relevance gate" className="w-40">
              {(p) => (
                <Select
                  {...p}
                  value={gateBand}
                  onChange={(e) => setGateBand(e.target.value)}
                  className="h-8 text-xs"
                >
                  <option value="">Any</option>
                  {Object.entries(GATE_BAND_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>

            <Field label="Run" className="w-48">
              {(p) => (
                <Select
                  {...p}
                  value={batchId}
                  onChange={(e) => setBatchId(e.target.value)}
                  className="h-8 text-xs"
                >
                  <option value="">All runs</option>
                  {(batchesQuery.data ?? []).map((b) => (
                    <option key={b.id} value={b.id}>
                      {formatRelative(b.created_at)} · {b.link_count} links
                    </option>
                  ))}
                </Select>
              )}
            </Field>

            <Field label="Search text" className="w-56">
              {(p) => (
                <Input
                  {...p}
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="mentos, crash, refund…"
                  className="h-8 text-xs"
                />
              )}
            </Field>

            {anyFilter && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setSource("");
                  setGateBand("");
                  setBatchId("");
                  setSearch("");
                }}
                className="mb-0.5"
              >
                Clear filters
              </Button>
            )}

            <p className="mb-2 ml-auto text-xs text-fg-muted" aria-live="polite">
              <span className="tnum font-medium text-fg">{docs.length.toLocaleString()}</span>{" "}
              loaded{docsQuery.hasNextPage && " so far"}
            </p>
          </div>

          <CardBody className="px-0 pb-0">
            {docsQuery.isLoading && <SkeletonList rows={5} className="px-5 py-5" />}

            {docsQuery.isError && (
              <div className="p-5">
                <Alert tone="danger" title="Couldn't load documents">
                  The backend didn&apos;t return this project&apos;s documents.
                </Alert>
              </div>
            )}

            {docsQuery.isSuccess && docs.length === 0 && (
              <EmptyState
                title={anyFilter ? "No documents match these filters" : "No documents yet"}
                description={
                  anyFilter
                    ? "Nothing in this project matches that combination. Try clearing a filter."
                    : "Extract some links first — everything collected shows up here, traceable to its source."
                }
                action={
                  anyFilter ? (
                    <Button
                      size="sm"
                      onClick={() => {
                        setSource("");
                        setGateBand("");
                        setBatchId("");
                        setSearch("");
                      }}
                    >
                      Clear filters
                    </Button>
                  ) : undefined
                }
              />
            )}

            {/* A list of per-source cards rather than one rigid table: a
                table forces every source through the same columns, which is
                what produced a Rating column reading "—" for YouTube while
                the like count it does have stayed hidden. */}
            {docs.length > 0 && (
              <div>
                {docs.map((doc) => (
                  <DocumentCard
                    key={doc.doc_id}
                    doc={doc}
                    profile={profileFor(profilesQuery.data?.profiles, doc.source)}
                    onOpen={() => setOpenDoc(doc)}
                  />
                ))}
              </div>
            )}

            {docsQuery.hasNextPage && (
              <div className="flex justify-center border-t border-line p-4">
                <Button
                  size="sm"
                  onClick={() => docsQuery.fetchNextPage()}
                  disabled={docsQuery.isFetchingNextPage}
                >
                  {docsQuery.isFetchingNextPage ? (
                    <>
                      <Spinner /> Loading…
                    </>
                  ) : (
                    `Load ${PAGE_SIZE} more`
                  )}
                </Button>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <DocumentDrawer doc={openDoc} onClose={() => setOpenDoc(null)} />
    </>
  );
}

function DocumentDrawer({ doc, onClose }: { doc: Doc | null; onClose: () => void }) {
  const open = doc !== null;

  // Escape closes, and the page behind stops scrolling while it's open —
  // without the lock, scrolling over the backdrop moves the list underneath,
  // which reads as the drawer sliding around.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!doc) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Document detail">
      <button
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/25 backdrop-blur-[1px]"
      />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-line bg-surface shadow-[var(--shadow-pop)]">
        <div className="sticky top-0 flex items-start justify-between gap-3 border-b border-line bg-surface px-5 py-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-fg">{sourceLabel(doc.source)}</p>
            <p className="mt-0.5 text-[11px] text-fg-subtle">{doc.doc_type}</p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} autoFocus>
            Close
          </Button>
        </div>

        <div className="px-5 py-4">
          {/* The title, where the source keeps one separately. App Store
              stores it in `subject`; Amazon and Flipkart fold it into the
              body, so those correctly show nothing here rather than an
              empty heading. */}
          {doc.subject && (
            <p className="mb-2 text-sm font-semibold text-fg">{doc.subject}</p>
          )}
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
            {doc.text ?? "(no text)"}
          </p>
        </div>

        <dl className="mt-auto grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line px-5 py-4 text-xs">
          {doc.engagement_count != null && (
            <Detail label={engagementLabel(doc)}>
              {doc.engagement_count.toLocaleString()}
            </Detail>
          )}
          {doc.product_id && <Detail label="Item">{doc.product_id}</Detail>}
          {doc.variant && <Detail label="Collected as">{doc.variant}</Detail>}
          {typeof doc.engagement?.app_version === "string" && (
            <Detail label="App version">{doc.engagement.app_version}</Detail>
          )}
          {doc.parent_id && (
            <Detail label="Reply to" hint="This document answers or replies to another">
              <span className="font-mono text-[10px]">
                {doc.parent_id.slice(0, 16)}…
              </span>
            </Detail>
          )}
          <Detail label="Lane" hint={doc.lane ? LANE_DESCRIPTIONS[doc.lane] : undefined}>
            {laneLabel(doc.lane)}
          </Detail>
          <Detail label="Extractor">{doc.extractor_version ?? "—"}</Detail>
          <Detail label="Rating">{doc.rating != null ? doc.rating.toFixed(1) : "—"}</Detail>
          <Detail label="Verified purchase">
            {doc.verified_purchase == null ? "—" : doc.verified_purchase ? "Yes" : "No"}
          </Detail>
          <Detail label="Captured">{formatDate(doc.captured_at)}</Detail>
          <Detail label="Authored">{formatDate(doc.authored_at)}</Detail>
          <Detail label="Language">{doc.lang ?? "—"}</Detail>
          <Detail label="Relevance gate">
            {doc.gate_band ? GATE_BAND_LABELS[doc.gate_band] ?? doc.gate_band : "—"}
          </Detail>
          <div className="col-span-2">
            <dt className="text-fg-subtle">Source URL</dt>
            <dd className="mt-0.5">
              <a
                href={doc.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all font-mono text-[11px] text-accent hover:underline"
              >
                {doc.source_url}
              </a>
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-fg-subtle">Document ID</dt>
            <dd className="mt-0.5 break-all font-mono text-[11px] text-fg-muted">{doc.doc_id}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

function Detail({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-fg-subtle" title={hint}>
        {label}
      </dt>
      <dd className="mt-0.5 text-fg">{children}</dd>
    </div>
  );
}

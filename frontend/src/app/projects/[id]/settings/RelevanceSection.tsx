"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Textarea } from "@/components/ui/Field";
import { Alert, Skeleton } from "@/components/ui/Feedback";
import { GATE_BAND_LABELS } from "@/lib/labels";

type Prototypes = {
  keep: string[];
  drop: string[];
  bands: { band: string; doc_count: number }[];
  document_count: number;
  starved: boolean;
};

const BAND_COLOR: Record<string, string> = {
  keep: "var(--success)",
  ambiguous: "var(--warn)",
  drop: "var(--fg-subtle)",
  ungated: "var(--line-strong)",
};

/**
 * The relevance gate's prototype sentences, editable.
 *
 * These have always been per-project and on disk, but nothing exposed
 * them — so a project keeps whatever the scaffold wrote until someone
 * finds the YAML. That matters more than it sounds: the gate decides what
 * the chatbot can retrieve (dropped documents are excluded), so prototypes
 * describing app crashes over a corpus of video comments quietly shrink
 * what the assistant can answer from.
 *
 * The copy insists on example sentences over category descriptions because
 * that was measured, not assumed: abstract descriptions produced
 * separation margins of 0.036 — inside the ±0.05 ambiguous band — and
 * pushed half a corpus into `ambiguous`, while concrete phrasings
 * separated at 0.17–0.40 (Docs/FEASIBILITY_LOG.md).
 */
export function RelevanceSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [keepText, setKeepText] = useState<string | null>(null);
  const [dropText, setDropText] = useState<string | null>(null);

  const gateQuery = useQuery({
    queryKey: ["gate-prototypes", projectId],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/gate/prototypes",
        { params: { path: { project_id: projectId } } }
      );
      if (error) throw error;
      return data as Prototypes;
    },
  });

  const loaded = gateQuery.data;
  // Derived, not synced through an effect: null means "not edited yet", so
  // the saved value shows through until the operator types. Copying the
  // fetched value into state on load would fight every refetch.
  const keepValue = keepText ?? loaded?.keep.join("\n") ?? "";
  const dropValue = dropText ?? loaded?.drop.join("\n") ?? "";

  const saveMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT(
        "/projects/{project_id}/gate/prototypes",
        {
          params: { path: { project_id: projectId } },
          body: {
            keep: keepValue.split("\n").map((s) => s.trim()).filter(Boolean),
            drop: dropValue.split("\n").map((s) => s.trim()).filter(Boolean),
          },
        }
      );
      if (error) throw error;
      return data as Prototypes;
    },
    onSuccess: () => {
      // Bands changed, so anything that reads them is stale: the gate
      // filter on the documents browser and every chart denominator.
      queryClient.invalidateQueries({ queryKey: ["gate-prototypes", projectId] });
      queryClient.invalidateQueries({ queryKey: ["documents", projectId] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
  });

  const total = loaded?.document_count ?? 0;
  const dropped = loaded?.bands.find((b) => b.band === "drop")?.doc_count ?? 0;
  const dropPct = total > 0 ? Math.round((dropped / total) * 100) : 0;
  // Compare the derived values, not the raw state: before the first edit
  // `keepText` is null, and `null !== "…"` would enable Save on load.
  const dirty =
    loaded != null &&
    (keepValue !== loaded.keep.join("\n") ||
      dropValue !== loaded.drop.join("\n"));

  return (
    <Card>
      <CardHeader
        title="Relevance"
        description="What counts as on-topic for this project. The gate scores every document against these examples; dropped documents stay in the export but are skipped by the chatbot."
      />
      <CardBody className="flex flex-col gap-4">
        {gateQuery.isPending && <Skeleton className="h-24 w-full" />}

        {loaded && (
          <>
            <div>
              <div className="mb-1.5 flex items-baseline justify-between text-xs">
                <span className="font-medium text-fg">Current split</span>
                <span className="tnum text-fg-subtle">
                  {total.toLocaleString()} documents
                </span>
              </div>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-sunken">
                {loaded.bands.map((b) => (
                  <div
                    key={b.band}
                    title={`${GATE_BAND_LABELS[b.band] ?? b.band}: ${b.doc_count}`}
                    style={{
                      width: `${total > 0 ? (b.doc_count / total) * 100 : 0}%`,
                      background: BAND_COLOR[b.band] ?? "var(--line-strong)",
                    }}
                  />
                ))}
              </div>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
                {loaded.bands.map((b) => (
                  <li key={b.band} className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="size-2 rounded-[2px]"
                      style={{ background: BAND_COLOR[b.band] ?? "var(--line-strong)" }}
                    />
                    <span className="text-fg-muted">
                      {GATE_BAND_LABELS[b.band] ?? b.band}
                    </span>
                    <span className="tnum font-medium text-fg">
                      {b.doc_count.toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {loaded.starved && (
              <Alert tone="warn" title="The gate is discarding nearly everything">
                {dropPct}% of this project&rsquo;s documents scored off-topic, and
                the chatbot only reads the rest. The starter examples below
                describe app reviews — if that isn&rsquo;t what you collected,
                replace them with sentences from your own data.
              </Alert>
            )}

            <Alert tone="info" title="Write examples, not rules">
              One sentence per line, phrased the way a real document would be.
              Category descriptions (&ldquo;text about a product problem&rdquo;)
              were measured separating at 0.036 — inside the ±0.05 undecided
              band — while concrete phrasings separated at 0.17–0.40.
            </Alert>

            <Field
              label="On-topic examples"
              hint="Documents similar to these are kept."
            >
              {(p) => (
                <Textarea
                  {...p}
                  rows={4}
                  value={keepValue}
                  onChange={(e) => setKeepText(e.target.value)}
                  placeholder={"The mentos truck crashing was the funniest part.\nI love how the two brands teamed up."}
                />
              )}
            </Field>

            <Field
              label="Off-topic examples"
              hint="Documents similar to these are dropped — spam, bots, moderation notices."
            >
              {(p) => (
                <Textarea
                  {...p}
                  rows={4}
                  value={dropValue}
                  onChange={(e) => setDropText(e.target.value)}
                  placeholder={"Subscribe to my channel, link in bio.\nThis comment was removed by a moderator."}
                />
              )}
            </Field>

            {saveMutation.isError && (
              <Alert tone="danger" title="Could not save">
                Both lists need at least one example — the gate scores the
                difference between them, so one empty side sends the whole
                project to a single band.
              </Alert>
            )}

            <div className="flex items-center gap-3">
              <Button
                variant="primary"
                disabled={!dirty || saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
              >
                {saveMutation.isPending ? "Re-scoring…" : "Save and re-score"}
              </Button>
              <p className="text-[11px] text-fg-subtle">
                Re-scores every document from stored embeddings — free, offline,
                and it never re-collects anything.
              </p>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

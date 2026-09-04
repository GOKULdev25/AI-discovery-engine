"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Feedback";
import { cn } from "@/components/ui/cn";

type Message = {
  id: string;
  role: string;
  content: string;
  citations: string[] | null;
  created_at: string;
};

/**
 * The chatbot, beside the charts rather than on its own tab.
 *
 * It states the scope it is answering over, and that scope is the same
 * filter driving the charts — so an answer can never silently describe a
 * different slice of the project than the chart next to it. Where the
 * relevance gate has dropped most of the corpus, that is said out loud:
 * retrieval excludes dropped documents, so a mis-tuned gate quietly
 * starves the chatbot, and the fix is on the Settings tab.
 */
export function ChatPane({
  projectId,
  batchId,
  source,
  scopeLabel,
  searchableCount,
  droppedCount,
}: {
  projectId: string;
  batchId: string;
  source: string;
  scopeLabel: string;
  searchableCount: number | null;
  droppedCount: number | null;
}) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const historyQuery = useQuery({
    queryKey: ["chat", projectId],
    queryFn: async () => {
      const { data, error } = await api.GET("/projects/{project_id}/chat", {
        params: { path: { project_id: projectId } },
      });
      if (error) throw error;
      return data as Message[];
    },
  });

  const askMutation = useMutation({
    mutationFn: async (q: string) => {
      const { data, error } = await api.POST("/projects/{project_id}/chat", {
        params: { path: { project_id: projectId } },
        // Scope travels with the question so the answer describes the
        // same slice the charts are showing.
        body: {
          question: q,
          ...(batchId ? { batch_id: batchId } : {}),
          ...(source ? { source } : {}),
        } as never,
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setQuestion("");
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] });
    },
  });

  const messages = historyQuery.data ?? [];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, askMutation.isPending]);

  const starved =
    droppedCount != null &&
    searchableCount != null &&
    searchableCount === 0 &&
    droppedCount > 0;

  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        title="Ask this data"
        description={
          searchableCount == null
            ? scopeLabel
            : `${scopeLabel} · ${searchableCount.toLocaleString()} searchable`
        }
      />

      {starved && (
        <div className="mx-5 mb-3 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-[11px] leading-relaxed text-fg">
          The relevance gate marked every document here off-topic, and
          retrieval skips dropped documents — so there is nothing for the
          chatbot to read. Tune the gate under <strong>Settings</strong>.
        </div>
      )}

      <div
        ref={scrollRef}
        className="mx-5 flex-1 overflow-y-auto rounded-lg bg-surface-sunken p-3"
        style={{ minHeight: "14rem", maxHeight: "26rem" }}
      >
        {messages.length === 0 && !askMutation.isPending && (
          <p className="px-1 py-6 text-center text-xs text-fg-subtle">
            Answers come only from the documents in scope, with citations.
          </p>
        )}
        <ul className="flex flex-col gap-3">
          {messages.map((m) => (
            <li
              key={m.id}
              className={cn(
                "max-w-[92%] rounded-lg px-3 py-2 text-xs leading-relaxed",
                m.role === "user"
                  ? "ml-auto bg-accent text-accent-fg"
                  : "bg-surface text-fg"
              )}
            >
              <p className="whitespace-pre-wrap">{m.content}</p>
              {m.citations && m.citations.length > 0 && (
                <p className="mt-1.5 text-[10px] opacity-80">
                  {m.citations.length} citation
                  {m.citations.length === 1 ? "" : "s"}
                </p>
              )}
            </li>
          ))}
          {askMutation.isPending && (
            <li className="flex items-center gap-2 text-xs text-fg-muted">
              <Spinner className="size-3.5" /> Reading the evidence…
            </li>
          )}
        </ul>
      </div>

      <form
        className="flex items-end gap-2 p-5 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          const q = question.trim();
          if (q) askMutation.mutate(q);
        }}
      >
        <Field label="Question" labelHidden className="flex-1">
          {(props) => (
            <Input
              {...props}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What do people complain about most?"
              disabled={askMutation.isPending}
            />
          )}
        </Field>
        <Button
          type="submit"
          variant="primary"
          disabled={askMutation.isPending || !question.trim()}
        >
          Ask
        </Button>
      </form>
    </Card>
  );
}

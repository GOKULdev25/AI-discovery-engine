"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { ProjectHeader } from "@/components/ProjectHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import { Alert, Spinner } from "@/components/ui/Feedback";
import { Popover } from "@/components/ui/Popover";
import { cn } from "@/components/ui/cn";
import { formatDate, laneLabel, sourceLabel } from "@/lib/labels";

type Message = {
  id: string;
  role: string;
  content: string;
  citations: string[] | null;
  created_at: string;
};

const STARTERS = [
  "What do people complain about most?",
  "What do reviewers praise?",
  "Are there recurring bug reports?",
  "How does sentiment differ by source?",
];

export function ChatClient({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const projectQuery = useQuery({
    queryKey: ["project-summary", projectId],
    queryFn: async () => {
      const { data, error } = await api.GET("/projects");
      if (error) throw error;
      return data.find((p) => p.id === projectId) ?? null;
    },
  });

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
        body: { question: q },
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
  const docCount = projectQuery.data?.document_count ?? 0;

  // Keep the newest turn in view — the previous transcript never scrolled, so a
  // long conversation silently grew past the bottom of the panel.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, askMutation.isPending]);

  function ask(q: string) {
    if (q.trim() && !askMutation.isPending) askMutation.mutate(q.trim());
  }

  return (
    <>
      <ProjectHeader projectId={projectId} />

      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-6">
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-fg">Ask the data</h2>
          <p className="mt-1 text-xs leading-relaxed text-fg-muted">
            Answers are grounded in{" "}
            <span className="tnum font-medium text-fg">{docCount.toLocaleString()}</span>{" "}
            extracted document{docCount === 1 ? "" : "s"} and cite the ones they came
            from. An ambiguous question gets a clarifying question, not a guess; thin
            evidence gets an honest decline.
          </p>
        </div>

        <Card className="overflow-hidden">
          <div
            ref={scrollRef}
            className="max-h-[62vh] min-h-[22rem] overflow-y-auto bg-surface-sunken p-4"
          >
            {messages.length === 0 && !historyQuery.isLoading && (
              <div className="flex h-full flex-col items-center justify-center gap-4 py-10 text-center">
                <div>
                  <p className="text-sm font-medium text-fg">Nothing asked yet</p>
                  <p className="mx-auto mt-1 max-w-xs text-xs leading-relaxed text-fg-muted">
                    {docCount === 0
                      ? "This project has no documents yet — extract some links first."
                      : "Try one of these, or write your own."}
                  </p>
                </div>
                {docCount > 0 && (
                  <div className="flex flex-wrap justify-center gap-2">
                    {STARTERS.map((s) => (
                      <button
                        key={s}
                        onClick={() => ask(s)}
                        disabled={askMutation.isPending}
                        className="rounded-full border border-line bg-surface px-3 py-1.5 text-xs
                                   text-fg-muted transition-colors hover:border-accent-line
                                   hover:bg-accent-soft hover:text-accent disabled:opacity-50"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-col gap-4" aria-live="polite">
              {messages.map((m) => (
                <MessageBubble key={m.id} projectId={projectId} message={m} />
              ))}
              {askMutation.isPending && (
                <div className="flex items-center gap-2 text-xs text-fg-muted">
                  <Spinner /> Searching the evidence…
                </div>
              )}
            </div>
          </div>

          <form
            className="flex items-end gap-2 border-t border-line bg-surface p-3"
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
          >
            <Field label="Your question" labelHidden className="flex-1">
              {(p) => (
                <Input
                  {...p}
                  placeholder="Ask a question grounded in this project's documents…"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  disabled={askMutation.isPending}
                  autoComplete="off"
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

        {askMutation.isError && (
          <Alert tone="danger" title="Couldn't get an answer" className="mt-3">
            The backend didn&apos;t respond. Check it&apos;s running, and that the AI
            budget isn&apos;t exhausted.
          </Alert>
        )}
      </div>
    </>
  );
}

function MessageBubble({ projectId, message }: { projectId: string; message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex flex-col gap-1.5", isUser ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
          isUser
            ? "rounded-br-md bg-accent text-accent-fg"
            : "rounded-bl-md border border-line bg-surface text-fg"
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
      </div>

      {message.citations && message.citations.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-fg-subtle">Cites</span>
          {message.citations.map((docId) => (
            <CitationBadge key={docId} projectId={projectId} docId={docId} />
          ))}
        </div>
      )}
    </div>
  );
}

function CitationBadge({ projectId, docId }: { projectId: string; docId: string }) {
  const [requested, setRequested] = useState(false);

  const docQuery = useQuery({
    queryKey: ["document", projectId, docId],
    enabled: requested,
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/projects/{project_id}/documents/{doc_id}",
        { params: { path: { project_id: projectId, doc_id: docId } } }
      );
      if (error) throw error;
      return data;
    },
  });

  return (
    <Popover
      width={340}
      trigger={(props) => (
        <button
          {...props}
          onClick={() => {
            setRequested(true);
            props.onClick();
          }}
          title="Open the cited document"
          className="rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px]
                     text-fg-muted transition-colors hover:border-accent-line hover:bg-accent-soft
                     hover:text-accent"
        >
          {docId.slice(0, 8)}
        </button>
      )}
    >
      {docQuery.isLoading && <p className="text-xs text-fg-subtle">Loading…</p>}
      {docQuery.isError && (
        <p className="text-xs text-danger">Couldn&apos;t load this document.</p>
      )}
      {docQuery.data && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2 text-[11px] text-fg-subtle">
            <span className="font-medium text-fg">{sourceLabel(docQuery.data.source)}</span>
            <span>{formatDate(docQuery.data.captured_at)}</span>
          </div>
          <p className="max-h-52 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-fg">
            {docQuery.data.text}
          </p>
          <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-line pt-2 text-[10px] text-fg-subtle">
            <span>Lane: {laneLabel(docQuery.data.lane)}</span>
            {docQuery.data.rating != null && <span>Rating: {docQuery.data.rating}</span>}
            <a
              href={docQuery.data.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            >
              Open source ↗
            </a>
          </div>
        </div>
      )}
    </Popover>
  );
}

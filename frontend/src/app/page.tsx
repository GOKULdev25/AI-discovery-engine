"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import { Alert, EmptyState, SkeletonList } from "@/components/ui/Feedback";
import { Badge } from "@/components/ui/Badge";
import { formatRelative } from "@/lib/labels";

export default function HomePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [filter, setFilter] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: async () => {
      const { data, error } = await api.GET("/projects");
      if (error) throw error;
      return data;
    },
  });

  const createProject = useMutation({
    mutationFn: async (projectName: string) => {
      const { data, error } = await api.POST("/projects", {
        body: { name: projectName },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const projects = projectsQuery.data ?? [];
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = q ? projects.filter((p) => p.name.toLowerCase().includes(q)) : projects;
    return [...list].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [projects, filter]);

  const totalDocs = projects.reduce((sum, p) => sum + p.document_count, 0);

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-6">
      <header className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
          Competitive research, grounded in evidence
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">
          Paste links to reviews and discussion. Every document is extracted into one
          schema, kept traceable to its source, and answerable — with citations you
          can open.
        </p>
      </header>

      <Card className="mt-7">
        <CardBody className="pt-5">
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) createProject.mutate(name.trim());
            }}
          >
            <Field
              label="New project"
              hint="A project is a self-contained workspace — its own documents, settings, and browser session."
              className="flex-1"
            >
              {(fieldProps) => (
                <Input
                  {...fieldProps}
                  placeholder="e.g. Competitor Atlas"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="off"
                />
              )}
            </Field>
            <Button
              type="submit"
              variant="primary"
              disabled={createProject.isPending || !name.trim()}
              className="sm:mb-6"
            >
              {createProject.isPending ? "Creating…" : "Create project"}
            </Button>
          </form>

          {createProject.isError && (
            <Alert tone="danger" title="Couldn't create the project" className="mt-3">
              The backend didn&apos;t accept the request. Check it&apos;s running and
              reachable.
            </Alert>
          )}
        </CardBody>
      </Card>

      <section className="mt-10" aria-labelledby="projects-heading">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-2.5">
            <h2 id="projects-heading" className="text-sm font-semibold text-fg">
              Projects
            </h2>
            {projects.length > 0 && (
              <span className="tnum text-xs text-fg-subtle">
                {projects.length} · {totalDocs.toLocaleString()} documents
              </span>
            )}
          </div>
          {projects.length > 4 && (
            <Field label="Filter projects" labelHidden className="w-56">
              {(fieldProps) => (
                <Input
                  {...fieldProps}
                  type="search"
                  placeholder="Filter…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="h-8 text-xs"
                />
              )}
            </Field>
          )}
        </div>

        {projectsQuery.isLoading && <SkeletonList rows={3} />}

        {projectsQuery.isError && (
          <Alert tone="danger" title="Couldn't reach the backend">
            Nothing responded at the configured API URL. Start the backend, then
            reload.
          </Alert>
        )}

        {projectsQuery.isSuccess && projects.length === 0 && (
          <Card>
            <EmptyState
              title="No projects yet"
              description="Create one above, then paste your first batch of links to start collecting evidence."
              icon={
                <svg viewBox="0 0 24 24" className="size-7" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h9A1.5 1.5 0 0 1 21 10v7.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-10Z" />
                </svg>
              }
            />
          </Card>
        )}

        {projectsQuery.isSuccess && projects.length > 0 && visible.length === 0 && (
          <Card>
            <EmptyState
              title="No project matches that filter"
              description={`Nothing named like “${filter}”.`}
            />
          </Card>
        )}

        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((project) => (
            <li key={project.id}>
              <Link
                href={`/projects/${project.id}`}
                className="group flex h-full flex-col rounded-xl border border-line bg-surface p-4
                           shadow-[var(--shadow-card)] transition-all
                           hover:-translate-y-0.5 hover:border-line-strong hover:shadow-[var(--shadow-pop)]"
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="min-w-0 truncate font-medium text-fg group-hover:text-accent">
                    {project.name}
                  </h3>
                  {project.session_mode === "operator_session" && (
                    <Badge tone="info">Operator</Badge>
                  )}
                </div>

                <div className="mt-4 flex items-baseline gap-4">
                  <div>
                    <div className="tnum text-xl font-semibold tracking-tight text-fg">
                      {project.document_count.toLocaleString()}
                    </div>
                    <div className="text-[11px] text-fg-subtle">documents</div>
                  </div>
                  <div>
                    <div className="tnum text-xl font-semibold tracking-tight text-fg-muted">
                      {project.batch_count.toLocaleString()}
                    </div>
                    <div className="text-[11px] text-fg-subtle">
                      {project.batch_count === 1 ? "batch" : "batches"}
                    </div>
                  </div>
                </div>

                <p className="mt-auto pt-4 text-[11px] text-fg-subtle">
                  Created {formatRelative(project.created_at)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

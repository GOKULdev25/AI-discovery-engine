"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ProjectHeader } from "@/components/ProjectHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import { Alert, Skeleton } from "@/components/ui/Feedback";
import { cn } from "@/components/ui/cn";
import { RelevanceSection } from "./RelevanceSection";

const SESSION_MODES = [
  {
    value: "logged_out",
    label: "Logged out",
    description:
      "The default. Collects only what a signed-out visitor can see. Nothing about this project ever touches an account.",
  },
  {
    value: "operator_session",
    label: "Operator session",
    description:
      "Attaches to a Chrome you started yourself with remote debugging enabled and signed into manually. The app never sees a credential — but what it collects is then scoped to your own account, which is a decision to make deliberately, per project.",
  },
] as const;

export function SettingsClient({ projectId }: { projectId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [sessionMode, setSessionMode] = useState<string | null>(null);
  const [localesText, setLocalesText] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState("");

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

  // Seed the form once, then let it be user-controlled — re-seeding on every
  // refetch would stomp whatever is being typed.
  useEffect(() => {
    if (project && sessionMode === null) {
      setSessionMode(project.session_mode);
      setLocalesText((project.locales ?? []).join(", "));
    }
  }, [project, sessionMode]);

  const save = useMutation({
    mutationFn: async () => {
      const locales = (localesText ?? "")
        .split(",")
        .map((l) => l.trim().toLowerCase())
        .filter(Boolean);
      const { data, error } = await api.PATCH("/projects/{project_id}", {
        params: { path: { project_id: projectId } },
        body: {
          session_mode: sessionMode as "logged_out" | "operator_session",
          locales,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const remove = useMutation({
    mutationFn: async () => {
      const { error } = await api.DELETE("/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push("/");
    },
  });

  const dirty =
    project != null &&
    (sessionMode !== project.session_mode ||
      localesText !== (project.locales ?? []).join(", "));

  return (
    <>
      <ProjectHeader projectId={projectId} />

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-5 py-8 sm:px-6">
        <Card>
          <CardHeader
            title="Collection mode"
            description="How this project's browser lane reaches pages that need a session."
          />
          <CardBody className="flex flex-col gap-2.5">
            {projectQuery.isLoading && <Skeleton className="h-24 w-full" />}
            {SESSION_MODES.map((mode) => {
              const active = sessionMode === mode.value;
              return (
                <label
                  key={mode.value}
                  className={cn(
                    "flex cursor-pointer gap-3 rounded-lg border p-3.5 transition-colors",
                    active
                      ? "border-accent-line bg-accent-soft"
                      : "border-line hover:bg-surface-hover"
                  )}
                >
                  <input
                    type="radio"
                    name="session_mode"
                    value={mode.value}
                    checked={active}
                    onChange={() => setSessionMode(mode.value)}
                    className="mt-0.5 accent-[var(--accent)]"
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-fg">{mode.label}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-fg-muted">
                      {mode.description}
                    </span>
                  </span>
                </label>
              );
            })}
          </CardBody>
        </Card>

        <RelevanceSection projectId={projectId} />

        <Card>
          <CardHeader
            title="Locales"
            description="Which storefronts / regions the App Store and Play Store connectors fan out across. Two-letter country codes, comma separated."
          />
          <CardBody>
            <Field
              label="Locales"
              labelHidden
              hint="A conservative default (us, in, gb) — every extra locale multiplies the requests a batch spends."
            >
              {(p) =>
                localesText === null ? (
                  <Skeleton className="h-9.5 w-full" />
                ) : (
                  <Input
                    {...p}
                    value={localesText}
                    onChange={(e) => setLocalesText(e.target.value)}
                    placeholder="us, in, gb"
                  />
                )
              }
            </Field>
          </CardBody>
        </Card>

        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save changes"}
          </Button>
          {save.isSuccess && !dirty && (
            <span className="text-xs text-success">Saved.</span>
          )}
          {dirty && <span className="text-xs text-fg-subtle">Unsaved changes</span>}
        </div>

        {save.isError && (
          <Alert tone="danger" title="Couldn't save">
            The backend rejected the update.
          </Alert>
        )}

        <Card tone="danger">
          <CardHeader
            title="Delete this project"
            description="Removes the project directory, its warehouse, its browser profile, and everything extracted into it. This cannot be undone."
          />
          <CardBody className="flex flex-col gap-3">
            <Field label={`Type “${project?.name ?? ""}” to confirm`}>
              {(p) => (
                <Input
                  {...p}
                  value={confirmName}
                  onChange={(e) => setConfirmName(e.target.value)}
                  placeholder={project?.name ?? ""}
                  autoComplete="off"
                />
              )}
            </Field>
            <div>
              <Button
                variant="danger"
                disabled={!project || confirmName !== project.name || remove.isPending}
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? "Deleting…" : "Delete project"}
              </Button>
            </div>
            {remove.isError && (
              <Alert tone="danger" title="Couldn't delete">
                The backend rejected the request.
              </Alert>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}

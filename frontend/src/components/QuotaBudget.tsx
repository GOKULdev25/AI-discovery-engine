"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "./ui/Badge";
import { Meter } from "./ui/Progress";
import { Popover } from "./ui/Popover";
import { Skeleton } from "./ui/Feedback";
import { cn } from "./ui/cn";

type Window = { used: number; limit: number | null; remaining: number | null };

/**
 * Remaining daily AI budget (A§7.3, A§13 `GET /quota`) — shown before a batch
 * starts so a long classification run doesn't die halfway through unexplained.
 * App-level, not project-scoped: every project draws from the same pool.
 *
 * Now a compact pill that opens a per-provider breakdown, rather than a wall of
 * text in the page header. The "10% left" amber rule is unchanged.
 */
export function QuotaBudget() {
  const quotaQuery = useQuery({
    queryKey: ["quota"],
    queryFn: async () => {
      const { data, error } = await api.GET("/quota");
      if (error) throw error;
      return data;
    },
    refetchInterval: 15_000,
  });

  if (quotaQuery.isLoading) return <Skeleton className="h-6.5 w-28" />;
  if (quotaQuery.isError || !quotaQuery.data) return null; // non-critical — never block the page

  const providers = [
    { label: "Gemini", rpd: quotaQuery.data.gemini.rpd as Window },
    { label: "Groq", rpd: quotaQuery.data.groq.rpd as Window },
  ];

  const metered = providers.filter((p) => p.rpd.limit !== null && p.rpd.remaining !== null);
  const spent = metered.filter((p) => p.rpd.remaining! <= 0);
  const low = metered.filter((p) => p.rpd.remaining! > 0 && p.rpd.remaining! <= p.rpd.limit! * 0.1);
  const allSpent = metered.length > 0 && spent.length === metered.length;

  // Naming the constrained provider beats a single blended percentage: the
  // providers are separate pools with separate roles (A§11.1 — Gemini does bulk
  // classification, Groq answers chat), so "37%" across both would describe
  // nothing real.
  const tone = allSpent ? "danger" : spent.length > 0 || low.length > 0 ? "warn" : "neutral";
  const summary = allSpent
    ? "AI budget spent"
    : spent.length > 0
      ? `${spent[0].label} exhausted`
      : low.length > 0
        ? `${low[0].label} low`
        : "AI budget OK";

  return (
    <Popover
      width={280}
      align="end"
      trigger={(props) => (
        <button
          {...props}
          className="rounded-full focus-visible:outline-2"
          title="Daily AI request budget"
        >
          <Badge tone={tone} className="cursor-pointer hover:brightness-97">
            <span
              aria-hidden
              className={cn(
                "size-1.5 rounded-full",
                allSpent ? "bg-danger" : tone === "warn" ? "bg-warn" : "bg-success"
              )}
            />
            {summary}
          </Badge>
        </button>
      )}
    >
      <p className="text-xs font-semibold text-fg mb-1">Daily AI budget</p>
      <p className="text-[11px] text-fg-muted leading-relaxed mb-3">
        Shared across every project — requests left today on each free tier.
      </p>
      <div className="flex flex-col gap-3">
        {providers.map((p) => (
          <ProviderRow key={p.label} label={p.label} rpd={p.rpd} />
        ))}
      </div>
    </Popover>
  );
}

function ProviderRow({ label, rpd }: { label: string; rpd: Window }) {
  if (rpd.limit === null || rpd.remaining === null) {
    return (
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-fg">{label}</span>
        <span className="text-fg-subtle">unmetered</span>
      </div>
    );
  }
  const low = rpd.remaining <= rpd.limit * 0.1;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-fg">{label}</span>
        <span className={cn("tnum", low ? "text-warn font-medium" : "text-fg-muted")}>
          {rpd.remaining.toLocaleString()}
          <span className="text-fg-subtle"> / {rpd.limit.toLocaleString()} left</span>
        </span>
      </div>
      <Meter used={rpd.used} limit={rpd.limit} tone={low ? "warn" : "accent"} />
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { cn } from "./ui/cn";

type Choice = "light" | "system" | "dark";

const STORAGE_KEY = "ade-theme";

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyChoice(choice: Choice) {
  const resolved = choice === "system" ? (systemPrefersDark() ? "dark" : "light") : choice;
  document.documentElement.dataset.theme = resolved;
  if (choice === "system") localStorage.removeItem(STORAGE_KEY);
  else localStorage.setItem(STORAGE_KEY, choice);
}

const OPTIONS: { value: Choice; label: string; icon: React.ReactNode }[] = [
  {
    value: "light",
    label: "Light",
    icon: (
      <svg viewBox="0 0 16 16" className="size-3.5" fill="currentColor" aria-hidden>
        <path d="M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm0-9.5a.75.75 0 0 1 .75.75v1a.75.75 0 0 1-1.5 0v-1A.75.75 0 0 1 8 1.5Zm0 11a.75.75 0 0 1 .75.75v1a.75.75 0 0 1-1.5 0v-1A.75.75 0 0 1 8 12.5ZM14.5 8a.75.75 0 0 1-.75.75h-1a.75.75 0 0 1 0-1.5h1a.75.75 0 0 1 .75.75Zm-11 0a.75.75 0 0 1-.75.75h-1a.75.75 0 0 1 0-1.5h1A.75.75 0 0 1 3.5 8Zm9.06-4.56a.75.75 0 0 1 0 1.06l-.7.71a.75.75 0 1 1-1.07-1.06l.71-.71a.75.75 0 0 1 1.06 0ZM5.2 10.8a.75.75 0 0 1 0 1.06l-.7.71a.75.75 0 0 1-1.07-1.06l.71-.71a.75.75 0 0 1 1.06 0Zm7.36 1.77a.75.75 0 0 1-1.06 0l-.71-.7a.75.75 0 1 1 1.06-1.07l.71.71a.75.75 0 0 1 0 1.06ZM5.2 5.2a.75.75 0 0 1-1.06 0l-.71-.7A.75.75 0 0 1 4.5 3.43l.71.71a.75.75 0 0 1 0 1.06Z" />
      </svg>
    ),
  },
  {
    value: "system",
    label: "System",
    icon: (
      <svg viewBox="0 0 16 16" className="size-3.5" fill="currentColor" aria-hidden>
        <path d="M2 3.75A1.75 1.75 0 0 1 3.75 2h8.5A1.75 1.75 0 0 1 14 3.75v6.5A1.75 1.75 0 0 1 12.25 12H9.2l.3 1.5h1.25a.75.75 0 0 1 0 1.5h-5.5a.75.75 0 0 1 0-1.5H6.5l.3-1.5H3.75A1.75 1.75 0 0 1 2 10.25v-6.5Zm1.75-.25a.25.25 0 0 0-.25.25v6.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25v-6.5a.25.25 0 0 0-.25-.25h-8.5Z" />
      </svg>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    icon: (
      <svg viewBox="0 0 16 16" className="size-3.5" fill="currentColor" aria-hidden>
        <path d="M6.2 2.1a.75.75 0 0 1 .2.95A4.9 4.9 0 0 0 13 9.6a.75.75 0 0 1 1 .86A6.4 6.4 0 1 1 5.35 1.9a.75.75 0 0 1 .85.2Z" />
      </svg>
    ),
  },
];

export function ThemeToggle() {
  // `null` until mounted: the server has no idea what the browser chose, so
  // rendering a "selected" state before hydration would guess wrong and flash.
  const [choice, setChoice] = useState<Choice | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as Choice | null;
    setChoice(stored ?? "system");
  }, []);

  // Only matters while following the system: re-resolve if the OS flips.
  useEffect(() => {
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyChoice("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [choice]);

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5"
    >
      {OPTIONS.map((opt) => {
        const active = choice === opt.value;
        return (
          <button
            key={opt.value}
            role="radio"
            aria-checked={active}
            aria-label={opt.label}
            title={opt.label}
            onClick={() => {
              setChoice(opt.value);
              applyChoice(opt.value);
            }}
            className={cn(
              "inline-flex size-6.5 items-center justify-center rounded-md transition-colors",
              active
                ? "bg-surface-sunken text-fg"
                : "text-fg-subtle hover:text-fg-muted"
            )}
          >
            {opt.icon}
          </button>
        );
      })}
    </div>
  );
}

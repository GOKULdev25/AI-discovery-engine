"use client";

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { cn } from "./cn";

/**
 * A dependency-free popover.
 *
 * The citation popover it replaces had no dismissal at all — no outside click,
 * no Escape, no focus return — and could render off the right edge of the
 * viewport. This handles all four, and flips/clamps horizontally so a citation
 * near the window edge stays readable.
 */
export function Popover({
  trigger,
  children,
  className,
  align = "start",
  width = 320,
}: {
  trigger: (props: {
    onClick: () => void;
    "aria-expanded": boolean;
    "aria-haspopup": "dialog";
    "aria-controls"?: string;
    ref: React.Ref<HTMLButtonElement>;
  }) => ReactNode;
  children: ReactNode;
  className?: string;
  align?: "start" | "end";
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [offsetX, setOffsetX] = useState(0);
  const [flipUp, setFlipUp] = useState(false);
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback(
    (returnFocus: boolean) => {
      setOpen(false);
      if (returnFocus) triggerRef.current?.focus();
    },
    []
  );

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (panelRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      close(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close(true);
      }
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, close]);

  // Measured before paint so the panel never appears in the wrong place first.
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const margin = 8;

    const naturalLeft = align === "end" ? rect.right - width : rect.left;
    let dx = 0;
    if (naturalLeft < margin) dx = margin - naturalLeft;
    else if (naturalLeft + width > window.innerWidth - margin) {
      dx = window.innerWidth - margin - width - naturalLeft;
    }
    setOffsetX(dx);
    setFlipUp(rect.bottom + 240 > window.innerHeight && rect.top > 260);
  }, [open, align, width]);

  return (
    <span className="relative inline-block">
      {trigger({
        onClick: () => setOpen((o) => !o),
        "aria-expanded": open,
        "aria-haspopup": "dialog",
        "aria-controls": open ? panelId : undefined,
        ref: triggerRef,
      })}
      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          style={{ width, transform: `translateX(${offsetX}px)` }}
          className={cn(
            "absolute z-50 rounded-xl border border-line bg-surface-raised",
            "shadow-[var(--shadow-pop)] p-3 text-left",
            flipUp ? "bottom-full mb-1.5" : "top-full mt-1.5",
            align === "end" ? "right-0" : "left-0",
            className
          )}
        >
          {children}
        </div>
      )}
    </span>
  );
}

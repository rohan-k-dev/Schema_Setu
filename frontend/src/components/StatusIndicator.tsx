"use client";

import React, { useEffect, useState } from "react";
import { healthCheck } from "@/lib/api";

type Health = "checking" | "healthy" | "degraded" | "offline";

const STYLES: Record<Health, { dot: string; label: string }> = {
  checking: { dot: "bg-slate-300", label: "Connecting…" },
  healthy: { dot: "bg-green-400", label: "System ready" },
  degraded: { dot: "bg-amber-400", label: "Limited service" },
  offline: { dot: "bg-red-400", label: "Server unreachable" },
};

/**
 * Connection status from GET /health (polled every 30 s).
 * "Limited service" = backend up but database or knowledge graph unavailable.
 * Shows only a coarse status — no internal details (§110).
 */
export default function StatusIndicator({ onDemoMode }: { onDemoMode?: (demo: boolean) => void }) {
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const h = await healthCheck();
        if (cancelled) return;
        setHealth(h.status === "healthy" ? "healthy" : "degraded");
        onDemoMode?.(h.environment === "demo");
      } catch {
        if (!cancelled) setHealth("offline");
      }
    };
    check();
    const timer = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [onDemoMode]);

  const { dot, label } = STYLES[health];
  return (
    <div
      className="flex items-center gap-1.5 bg-white/10 px-2.5 py-1.5 rounded-full text-xs"
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      <span className="text-emerald-100 hidden sm:inline">{label}</span>
    </div>
  );
}

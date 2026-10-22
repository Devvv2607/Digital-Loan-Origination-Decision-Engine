"use client";

import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { onServerWaking, warmUpServer } from "@/lib/api";

/**
 * Friendly notice while the free-tier API wakes from sleep (it can take up to a minute).
 * Also starts waking the server as soon as any page loads.
 */
export function ServerWakeNotice() {
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    const unsubscribe = onServerWaking(setWaking);
    warmUpServer();
    return unsubscribe;
  }, []);

  return (
    <div role="status" aria-live="polite" className={waking ? "fixed inset-x-4 bottom-4 z-50 flex justify-center" : "sr-only"}>
      {waking ? (
        <p className="flex max-w-xl items-start gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm shadow-lg">
          <LoaderCircle className="mt-0.5 size-4 shrink-0 animate-spin text-primary" aria-hidden />
          <span>
            <strong className="font-semibold">Waking up the demo server, this can take up to a minute.</strong>{" "}
            <span className="text-muted-foreground">It sleeps when nobody is using it. Your progress is kept.</span>
          </span>
        </p>
      ) : null}
    </div>
  );
}

"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Step wrapper: moves focus to the heading when a step appears, for keyboard and screen-reader users. */
export function StepShell({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: React.ReactNode;
  children: React.ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section aria-labelledby="step-title" className="space-y-6">
      <div className="space-y-2">
        <h1 id="step-title" ref={heading} tabIndex={-1} className="text-2xl font-semibold tracking-tight outline-none">
          {title}
        </h1>
        {intro ? <div className="max-w-prose text-[0.95rem] leading-relaxed text-muted-foreground">{intro}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** Primary action. Shows a spinner and a specific "what's happening" label while a mock call runs. */
export function ActionButton({
  busy,
  busyLabel,
  children,
  variant = "default",
  className,
  ...props
}: React.ComponentProps<typeof Button> & { busy?: boolean; busyLabel?: string }) {
  return (
    <Button
      {...props}
      variant={variant}
      disabled={busy || props.disabled}
      aria-busy={busy || undefined}
      className={cn("h-11 w-full px-5 text-[0.95rem] sm:w-auto", className)}
    >
      {busy ? (
        <>
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          {busyLabel ?? children}
        </>
      ) : (
        children
      )}
    </Button>
  );
}

export function ErrorNotice({ title, message }: { title?: string; message: string | null }) {
  if (!message) return null;
  return (
    <Alert variant="destructive" role="alert">
      {title ? <AlertTitle>{title}</AlertTitle> : null}
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

const TONES = {
  info: "border-border bg-card",
  refer: "border-refer/30 bg-refer-soft",
  approve: "border-approve/30 bg-approve-soft",
  decline: "border-decline/30 bg-decline-soft",
} as const;

export function Notice({
  tone = "info",
  title,
  children,
  live,
}: {
  tone?: keyof typeof TONES;
  title?: string;
  children: React.ReactNode;
  live?: boolean;
}) {
  return (
    <div
      role={live ? "status" : undefined}
      className={cn("rounded-lg border px-4 py-3 text-[0.925rem] leading-relaxed", TONES[tone])}
    >
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-1" : undefined}>{children}</div>
    </div>
  );
}

/** A simulated code shown on screen instead of an SMS, with a one-tap fill. */
export function SimulatedCode({ code, onUse, label }: { code: string; onUse: () => void; label: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-input bg-muted px-4 py-3">
      <p className="text-sm">
        {label} <span className="figures ml-1 text-base font-semibold tracking-[0.2em]">{code}</span>
        <span className="block text-xs text-muted-foreground">Simulated. No SMS was sent.</span>
      </p>
      <Button type="button" variant="outline" className="h-9" onClick={onUse}>
        Fill in the code
      </Button>
    </div>
  );
}

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-xs font-medium text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** aria props tying an input to its hint/error text. */
export function describe(id: string, error?: string, hint?: string) {
  return {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? `${id}-error` : hint ? `${id}-hint` : undefined,
  } as const;
}

export const inputClass = "h-11 text-base";
export const selectClass =
  "h-11 w-full rounded-lg border border-input bg-card px-3 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive";

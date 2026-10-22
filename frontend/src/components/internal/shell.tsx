"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Eye, LoaderCircle, LogOut, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";

import { InternalAuthProvider, useInternalAuth } from "./auth";

const TABS = [
  { href: "/internal/metrics", label: "Metrics", who: "Product manager" },
  { href: "/internal/referrals", label: "Referral queue", who: "Credit ops analyst" },
  { href: "/internal/policy", label: "Credit policy", who: "Credit policy manager" },
];

export function InternalShell({ children }: { children: React.ReactNode }) {
  return (
    <InternalAuthProvider>
      <Shell>{children}</Shell>
    </InternalAuthProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Internal tools" className="-mx-1 flex gap-1 overflow-x-auto">
          {TABS.map((t) => {
            const active = pathname.startsWith(t.href);
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-11 shrink-0 items-center rounded-lg px-3 text-sm font-medium",
                  active ? "bg-card text-foreground shadow-[inset_0_0_0_1px_var(--border)]" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
        <AccessControl />
      </div>
      <div className="mt-6">{children}</div>
    </div>
  );
}

function AccessControl() {
  const { user, ready, signIn, signOut } = useInternalAuth();
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetState, setResetState] = useState<"idle" | "confirm" | "busy" | "done">("idle");

  if (!ready) return <div className="h-11" />;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
      setOpen(false);
      setPassword("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign in.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setResetState("busy");
    try {
      await api("/admin/demo/reset", { method: "POST", token: user?.token });
      setResetState("done");
      window.setTimeout(() => window.location.reload(), 800);
    } catch {
      setResetState("idle");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {user ? (
        <>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-approve/30 bg-approve-soft px-3 py-1 text-approve">
            <ShieldCheck className="size-4" aria-hidden />
            Signed in as {user.role}
          </span>
          {user.role === "admin" ? (
            resetState === "confirm" ? (
              <span className="inline-flex items-center gap-2">
                Restore the starting demo data? New applications and policy edits are removed.
                <Button variant="destructive" className="h-11 px-3" onClick={reset}>Yes, reset</Button>
                <Button variant="ghost" className="h-11 px-3" onClick={() => setResetState("idle")}>Cancel</Button>
              </span>
            ) : (
              <Button variant="outline" className="h-11 px-3" disabled={resetState !== "idle"}
                onClick={() => setResetState("confirm")}>
                {resetState === "busy" ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : null}
                {resetState === "done" ? "Demo data reset" : "Reset demo data"}
              </Button>
            )
          ) : null}
          <Button variant="ghost" className="h-11 px-3" onClick={signOut}>
            <LogOut className="size-4" aria-hidden />
            Sign out
          </Button>
        </>
      ) : (
        <>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-muted-foreground">
            <Eye className="size-4" aria-hidden />
            Read-only demo view
          </span>
          <Button variant="outline" className="h-11 px-3" onClick={() => setOpen(true)}>
            Sign in to make changes
          </Button>
        </>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={submit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>Sign in as ops or admin</DialogTitle>
              <DialogDescription>
                Credentials are set by whoever runs this demo (environment variables). Without them you can still
                browse every screen read-only.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5">
              <label htmlFor="int-user" className="text-sm font-medium">Username</label>
              <Input id="int-user" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className="h-11" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="int-pass" className="text-sm font-medium">Password</label>
              <Input id="int-pass" type="password" autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} className="h-11" />
            </div>
            {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
            <DialogFooter>
              <Button type="submit" className="h-11 px-4" disabled={busy || !username || !password}>
                {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : null}
                Sign in
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function PageTitle({ title, intro }: { title: string; intro?: string }) {
  const tab = TABS.find((t) => t.label === title);
  return (
    <div className="mb-6 max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {intro ? <p className="mt-1.5 text-muted-foreground">{intro}</p> : null}
      {tab ? <p className="mt-1 text-sm text-muted-foreground">Used by: {tab.who}</p> : null}
    </div>
  );
}

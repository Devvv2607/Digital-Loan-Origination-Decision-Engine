"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { saveSession } from "@/lib/session";
import type { Persona } from "@/lib/types";

interface PersonaSummary {
  persona_id: string;
  label: string;
  applicant_name: string;
  description: string;
  expected_outcome: string;
}

export function PersonaList() {
  const router = useRouter();
  const [items, setItems] = useState<PersonaSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    api<{ items: PersonaSummary[] }>("/demo/personas")
      .then(({ data }) => setItems(data.items))
      .catch((e: unknown) => setLoadError(e instanceof ApiError ? e.message : "Couldn't load the demo applicants."));
  }, []);

  async function start(id: string) {
    setStarting(id);
    setStartError(null);
    try {
      const { data } = await api<Persona>(`/demo/personas/${id}`, { method: "POST" });
      saveSession({ token: null, applicationId: null, persona: data });
      router.push("/apply");
    } catch (e) {
      setStartError(e instanceof ApiError ? e.message : "Couldn't start that applicant. Please try again.");
      setStarting(null);
    }
  }

  if (loadError) {
    return (
      <p role="alert" className="mt-6 rounded-lg border border-decline/30 bg-decline-soft px-4 py-3 text-sm">
        {loadError}
      </p>
    );
  }

  return (
    <div className="mt-6">
      {startError ? (
        <p role="alert" className="mb-4 rounded-lg border border-decline/30 bg-decline-soft px-4 py-3 text-sm">
          {startError}
        </p>
      ) : null}
      <ul className="divide-y divide-border rounded-xl border border-border bg-card" aria-busy={items === null}>
        {(items ?? Array.from({ length: 5 }, () => null)).map((p, i) =>
          p === null ? (
            <li key={i} className="h-24 animate-pulse bg-muted/40 motion-reduce:animate-none" />
          ) : (
            <li key={p.persona_id} className="grid gap-3 px-4 py-4 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-6 sm:px-5">
              <div className="min-w-0">
                <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground">
                  Fictional person · synthetic data
                </p>
                <p className="font-semibold">
                  {p.label}
                  <span className="font-normal text-muted-foreground">, {p.applicant_name}</span>
                </p>
                <p className="text-sm text-muted-foreground">{p.description}</p>
                <p className="mt-1.5 text-sm">
                  <span className="text-muted-foreground">What happens: </span>
                  {p.expected_outcome}
                </p>
              </div>
              <button
                type="button"
                onClick={() => start(p.persona_id)}
                disabled={starting !== null}
                aria-label={starting === p.persona_id ? undefined : `Try a sample applicant: ${p.applicant_name}`}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-primary/40 px-4 text-sm font-medium text-primary hover:bg-accent disabled:opacity-60"
              >
                {starting === p.persona_id ? (
                  <>
                    <LoaderCircle className="size-4 animate-spin" aria-hidden />
                    Preparing
                  </>
                ) : (
                  <>Try a sample applicant</>
                )}
              </button>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { clearSession, loadSession, saveSession, type Session } from "@/lib/session";
import type { ApplicationView, NextStep } from "@/lib/types";

import { AssessStep } from "./steps/assess-step";
import { ConsentStep } from "./steps/consent-step";
import { DecisionStep } from "./steps/decision-step";
import { DetailsStep } from "./steps/details-step";
import { EkycStep } from "./steps/ekyc-step";
import { ExpiredStep } from "./steps/expired-step";
import { OfferStage } from "./steps/offer-stage";
import { PanStep } from "./steps/pan-step";
import { PhoneStep } from "./steps/phone-step";
import { Progress } from "./progress";
import { ErrorNotice } from "./ui";

export type Stage =
  | "loading"
  | "phone"
  | "details"
  | "pan"
  | "ekyc"
  | "consent"
  | "assess"
  | "decision"
  | "offer"
  | "expired";

export function stageFor(next: NextStep): Stage {
  switch (next) {
    case "DETAILS":
    case "SUBMIT":
      return "details";
    case "PAN":
      return "pan";
    case "EKYC":
      return "ekyc";
    case "AA_CONSENT":
      return "consent";
    case "ASSESS":
      return "assess";
    case "OFFER":
    case "ESIGN":
    case "DISBURSE":
    case "DONE":
      return "offer";
    case "UNDER_REVIEW":
    case "DECISION":
      return "decision";
    case "START_NEW":
      return "expired";
  }
}

/** Everything a step needs: the session, the current application, and a way to move on. */
export interface FlowContext {
  session: Session;
  app: ApplicationView | null;
  setSession: (s: Session) => void;
  /** Re-read the application from the server and show the step it says comes next. */
  refresh: (applicationId?: string, sessionOverride?: Session) => Promise<void>;
  showDecision: () => void;
  startOver: () => void;
  /** The offer stage reports where it is (KFS, signing, done) so progress can show steps 7-8. */
  setOfferPhase: (phase: OfferPhase) => void;
}

export type OfferPhase = "kfs" | "sign" | "done";

export function ApplyFlow() {
  const [session, setSessionState] = useState<Session>({ token: null, applicationId: null, persona: null });
  const [app, setApp] = useState<ApplicationView | null>(null);
  const [stage, setStage] = useState<Stage>("loading");
  const [error, setError] = useState<string | null>(null);
  const [offerPhase, setOfferPhase] = useState<OfferPhase>("kfs");

  const setSession = useCallback((s: Session) => {
    setSessionState(s);
    saveSession(s);
  }, []);

  const refresh = useCallback(
    async (applicationId?: string, sessionOverride?: Session) => {
      const s = sessionOverride ?? loadSession();
      const id = applicationId ?? s.applicationId;
      if (!s.token || !id) {
        setStage("phone");
        return;
      }
      try {
        const { data } = await api<ApplicationView>(`/applications/${id}`, { token: s.token });
        setApp(data);
        setError(null);
        setStage(stageFor(data.next_step));
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404)) {
          // Session expired or belongs to someone else: verify the phone again; resume is offered there.
          const next = { ...s, token: null, applicationId: null };
          setSession(next);
          setApp(null);
          setStage("phone");
          return;
        }
        setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
      }
    },
    [setSession],
  );

  useEffect(() => {
    const s = loadSession();
    setSessionState(s);
    void refresh(undefined, s);
  }, [refresh]);

  const ctx: FlowContext = {
    session,
    app,
    setSession,
    refresh,
    showDecision: () => setStage("decision"),
    setOfferPhase,
    startOver: () => {
      clearSession();
      setSessionState({ token: null, applicationId: null, persona: null });
      setApp(null);
      setOfferPhase("kfs");
      setStage("phone");
    },
  };

  return (
    <div className="mx-auto w-full max-w-[38rem] px-4 py-8 sm:py-10">
      <Progress stage={stage} offerPhase={offerPhase} />
      {session.persona && stage !== "loading" ? <PersonaHint ctx={ctx} expanded={stage === "phone"} /> : null}
      <div className="mt-6">
        <ErrorNotice message={error} />
        {stage === "loading" ? <p className="text-muted-foreground">Loading your application</p> : null}
        {stage === "phone" ? <PhoneStep ctx={ctx} /> : null}
        {stage === "details" ? <DetailsStep ctx={ctx} /> : null}
        {stage === "pan" ? <PanStep ctx={ctx} /> : null}
        {stage === "ekyc" ? <EkycStep ctx={ctx} /> : null}
        {stage === "consent" ? <ConsentStep ctx={ctx} /> : null}
        {stage === "assess" ? <AssessStep ctx={ctx} /> : null}
        {stage === "decision" ? <DecisionStep ctx={ctx} /> : null}
        {stage === "offer" ? <OfferStage ctx={ctx} /> : null}
        {stage === "expired" ? <ExpiredStep ctx={ctx} /> : null}
      </div>
    </div>
  );
}

function PersonaHint({ ctx, expanded }: { ctx: FlowContext; expanded: boolean }) {
  const p = ctx.session.persona!;
  return (
    <details
      open={expanded}
      aria-label="Demo applicant"
      className="group mt-5 rounded-lg border border-primary/25 bg-accent text-sm text-accent-foreground"
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 [&::-webkit-details-marker]:hidden">
        <span>
          <span className="font-semibold">Applying as {p.details.full_name}</span> ({p.label.toLowerCase()})
        </span>
        <span className="shrink-0 text-xs underline underline-offset-2 group-open:hidden">What should happen?</span>
      </summary>
      <div className="space-y-1 px-4 pb-3">
        <p>The forms are filled in for you; just continue through each step.</p>
        <p>
          <span className="text-accent-foreground/80">What should happen: </span>
          {p.expected_outcome}
        </p>
      </div>
    </details>
  );
}

"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Field, Notice, SimulatedCode, StepShell, describe, inputClass } from "../ui";

interface Started {
  kyc_session_id: string;
  demo_kyc_otp: string | null;
}
interface Completed {
  status: "COMPLETE" | "DELAYED" | "INCOMPLETE";
  message: string | null;
}

export function EkycStep({ ctx }: { ctx: FlowContext }) {
  const [session, setSession] = useState<Started | null>(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState<"start" | "complete" | null>(null);
  const [outcome, setOutcome] = useState<Completed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/applications/${ctx.session.applicationId}/kyc`;

  async function start() {
    setError(null);
    setOutcome(null);
    setBusy("start");
    try {
      const { data } = await api<Started>(`${base}/start`, { method: "POST", token: ctx.session.token });
      setSession(data);
      setOtp("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start e-KYC.");
    } finally {
      setBusy(null);
    }
  }

  async function complete(e?: React.FormEvent) {
    e?.preventDefault();
    if (!session) return;
    setError(null);
    setBusy("complete");
    try {
      const { data } = await api<Completed>(`${base}/complete`, {
        method: "POST",
        token: ctx.session.token,
        body: { kyc_session_id: session.kyc_session_id, otp },
      });
      if (data.status === "COMPLETE") {
        await ctx.refresh();
        return;
      }
      setOutcome(data);
      if (data.status === "INCOMPLETE") setSession(null); // a fresh e-KYC attempt is needed
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't complete e-KYC.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <StepShell
      title="Complete e-KYC"
      intro="A simulated identity provider confirms your name, date of birth and address with a one-time code. No branch visit and no documents to upload."
    >
      {outcome?.status === "DELAYED" ? (
        <Notice tone="refer" title="The verification service isn't responding" live>
          {outcome.message} We tried three times. Your progress is saved; try again in a little while.
        </Notice>
      ) : null}
      {outcome?.status === "INCOMPLETE" ? (
        <Notice tone="refer" title="e-KYC didn't finish" live>
          {outcome.message} Start e-KYC again to get a new code.
        </Notice>
      ) : null}

      {session === null ? (
        <ActionButton busy={busy === "start"} busyLabel="Requesting a code" onClick={start}>
          {outcome?.status === "INCOMPLETE" ? "Start e-KYC again" : "Send e-KYC code"}
        </ActionButton>
      ) : (
        <form onSubmit={complete} className="space-y-4" noValidate>
          {session.demo_kyc_otp ? (
            <SimulatedCode label="Your e-KYC code is" code={session.demo_kyc_otp} onUse={() => setOtp(session.demo_kyc_otp!)} />
          ) : null}
          <Field id="kyc-otp" label="e-KYC code">
            <Input
              id="kyc-otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              className={`${inputClass} figures tracking-[0.3em]`}
              {...describe("kyc-otp")}
            />
          </Field>
          <ActionButton type="submit" disabled={otp.length !== 6} busy={busy === "complete"}
            busyLabel="Checking with the identity provider">
            {outcome?.status === "DELAYED" ? "Try again" : "Complete e-KYC"}
          </ActionButton>
        </form>
      )}
      <ErrorNotice message={error} />
    </StepShell>
  );
}

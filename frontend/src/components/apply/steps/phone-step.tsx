"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { dateTime, PHONE_PATTERN } from "@/lib/format";
import { deviceId } from "@/lib/session";
import type { Resumable } from "@/lib/types";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Field, SimulatedCode, StepShell, describe, inputClass } from "../ui";

const STEP_NAMES: Record<string, string> = {
  DETAILS: "your details",
  SUBMIT: "submitting your details",
  PAN: "PAN verification",
  EKYC: "e-KYC",
  AA_CONSENT: "the bank-data step",
  ASSESS: "your decision",
};

export function PhoneStep({ ctx }: { ctx: FlowContext }) {
  const [phone, setPhone] = useState(ctx.session.persona?.phone ?? "");
  const [phoneError, setPhoneError] = useState<string>();
  const [demoOtp, setDemoOtp] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState<"send" | "verify" | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resumable, setResumable] = useState<{ token: string; items: Resumable[] } | null>(null);

  async function sendCode(e?: React.FormEvent) {
    e?.preventDefault();
    setError(null);
    if (!PHONE_PATTERN.test(phone)) {
      setPhoneError("Enter a 10-digit mobile number starting with 6, 7, 8 or 9.");
      return;
    }
    setPhoneError(undefined);
    setBusy("send");
    try {
      const { data } = await api<{ demo_otp: string | null }>("/auth/otp/send", {
        method: "POST",
        body: { phone },
      });
      setDemoOtp(data.demo_otp);
      setOtp("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send a code.");
    } finally {
      setBusy(null);
    }
  }

  async function createApplication(token: string) {
    setBusy("create");
    try {
      const { data } = await api<{ id: string }>("/applications", {
        method: "POST",
        token,
        headers: { "X-Device-Id": deviceId() },
      });
      const session = { ...ctx.session, token, applicationId: data.id };
      ctx.setSession(session);
      await ctx.refresh(data.id, session);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start your application.");
      setBusy(null);
    }
  }

  async function resume(token: string, id: string) {
    const session = { ...ctx.session, token, applicationId: id };
    ctx.setSession(session);
    await ctx.refresh(id, session);
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("verify");
    try {
      const { data } = await api<{ access_token: string; resumable_applications: Resumable[] }>("/auth/otp/verify", {
        method: "POST",
        body: { phone, otp },
      });
      if (!ctx.session.persona && data.resumable_applications.length > 0) {
        setResumable({ token: data.access_token, items: data.resumable_applications });
        setBusy(null);
        return;
      }
      await createApplication(data.access_token);
    } catch (err) {
      if (err instanceof ApiError && err.code === "OTP_INVALID" && typeof err.details.attempts_remaining === "number") {
        const n = err.details.attempts_remaining;
        setError(`${err.message} ${n} ${n === 1 ? "attempt" : "attempts"} left before a 15-minute lock.`);
      } else {
        setError(err instanceof ApiError ? err.message : "Couldn't verify the code.");
      }
      setBusy(null);
    }
  }

  if (resumable) {
    return (
      <StepShell title="Pick up where you left off" intro="You have an application in progress on this number.">
        <ul className="space-y-3">
          {resumable.items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
              <div className="text-sm">
                <p className="font-medium">Next: {STEP_NAMES[r.next_step] ?? "continue"}</p>
                <p className="text-muted-foreground">Last updated {dateTime(r.last_activity_at)}</p>
              </div>
              <ActionButton className="sm:w-auto" onClick={() => resume(resumable.token, r.id)}>
                Continue this application
              </ActionButton>
            </li>
          ))}
        </ul>
        <p className="text-sm text-muted-foreground">
          Applications you leave for 30 days expire.{" "}
          <button
            type="button"
            className="font-medium text-primary underline underline-offset-2"
            onClick={() => createApplication(resumable.token)}
          >
            Start a new application instead
          </button>
        </p>
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Verify your mobile number"
      intro="We use your number to keep your application safe and let you come back to it later."
    >
      <form onSubmit={sendCode} className="space-y-4" noValidate>
        <Field id="phone" label="Mobile number" hint="10 digits, without +91" error={phoneError}>
          <Input
            id="phone"
            inputMode="numeric"
            autoComplete="tel-national"
            maxLength={10}
            value={phone}
            onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
            className={inputClass}
            {...describe("phone", phoneError, "10 digits, without +91")}
          />
        </Field>
        {demoOtp === null ? (
          <ActionButton type="submit" busy={busy === "send"} busyLabel="Sending code">
            Send code
          </ActionButton>
        ) : null}
      </form>

      {demoOtp !== null ? (
        <form onSubmit={verify} className="space-y-4" noValidate>
          {demoOtp ? <SimulatedCode label="Your code is" code={demoOtp} onUse={() => setOtp(demoOtp)} /> : null}
          <Field id="otp" label="6-digit code" hint="The code is valid for 5 minutes.">
            <Input
              id="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              className={`${inputClass} figures tracking-[0.3em]`}
              {...describe("otp", undefined, "The code is valid for 5 minutes.")}
            />
          </Field>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <ActionButton
              type="submit"
              disabled={otp.length !== 6}
              busy={busy === "verify" || busy === "create"}
              busyLabel={busy === "create" ? "Starting your application" : "Checking code"}
            >
              Verify and continue
            </ActionButton>
            <button
              type="button"
              className="min-h-11 self-start text-sm font-medium text-primary underline underline-offset-2 disabled:opacity-50 sm:self-auto"
              onClick={() => sendCode()}
              disabled={busy !== null}
            >
              Send a new code
            </button>
          </div>
        </form>
      ) : null}
      <ErrorNotice message={error} />
    </StepShell>
  );
}

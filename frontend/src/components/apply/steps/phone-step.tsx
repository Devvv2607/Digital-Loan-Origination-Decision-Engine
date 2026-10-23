"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { PHONE_PATTERN } from "@/lib/format";
import type { MyApplications } from "@/lib/types";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Field, SimulatedCode, StepShell, describe, inputClass } from "../ui";

export function PhoneStep({ ctx }: { ctx: FlowContext }) {
  const [phone, setPhone] = useState(ctx.session.persona?.phone ?? "");
  const [phoneError, setPhoneError] = useState<string>();
  const [demoOtp, setDemoOtp] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState<"send" | "verify" | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      await ctx.newApplication(token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start your application.");
      setBusy(null);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("verify");
    try {
      const { data } = await api<{ access_token: string }>("/auth/otp/verify", {
        method: "POST",
        body: { phone, otp },
      });
      // A returning applicant sees "My applications" first; a new one goes straight to the form.
      const mine = await api<MyApplications>("/applications", { token: data.access_token });
      if (mine.data.items.length > 0) {
        const session = { ...ctx.session, token: data.access_token, applicationId: null };
        ctx.setSession(session);
        await ctx.refresh(undefined, session);
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

"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ApiError, api } from "@/lib/api";
import { PAN_PATTERN } from "@/lib/format";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Field, Notice, StepShell, describe, inputClass } from "../ui";

interface PanResult {
  status: "VERIFIED" | "NAME_CONFIRMATION_REQUIRED" | "INVALID" | "UNAVAILABLE";
  name_on_pan: string | null;
  name_entered: string | null;
  message: string | null;
}

const FORMAT_HINT = "5 letters, 4 digits, then 1 letter. For example ABCDE1234F.";

export function PanStep({ ctx }: { ctx: FlowContext }) {
  const [pan, setPan] = useState(ctx.session.persona?.pan ?? "");
  const [formatError, setFormatError] = useState<string>();
  const [result, setResult] = useState<PanResult | null>(null);
  const [choice, setChoice] = useState<"USE_PAN_NAME" | "KEEP_ENTERED_NAME">("USE_PAN_NAME");
  const [blocked, setBlocked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function verify(nameConfirmation?: string) {
    setError(null);
    setBlocked(null);
    // EC-03: check the format here first; a malformed PAN never reaches the PAN service.
    if (!PAN_PATTERN.test(pan)) {
      setFormatError(`That doesn't look like a PAN. ${FORMAT_HINT}`);
      return;
    }
    setFormatError(undefined);
    setBusy(true);
    try {
      const { data } = await api<PanResult>(`/applications/${ctx.session.applicationId}/pan/verify`, {
        method: "POST",
        token: ctx.session.token,
        body: nameConfirmation ? { pan, name_confirmation: nameConfirmation } : { pan },
      });
      if (data.status === "VERIFIED") {
        await ctx.refresh();
        return;
      }
      setResult(data);
    } catch (err) {
      if (err instanceof ApiError && err.code === "APPLICATION_ALREADY_IN_PROGRESS") {
        setBlocked(err.message);
      } else if (err instanceof ApiError && err.code === "PAN_FORMAT_INVALID") {
        setFormatError(err.message);
      } else {
        setError(err instanceof ApiError ? err.message : "Couldn't verify your PAN.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (result?.status === "NAME_CONFIRMATION_REQUIRED") {
    return (
      <StepShell
        title="Which is your legal name?"
        intro="The name on your PAN looks different from the one you entered. Pick the one on your official documents."
      >
        <RadioGroup value={choice} onValueChange={(v) => setChoice(v as typeof choice)} className="space-y-2">
          {[
            ["USE_PAN_NAME", result.name_on_pan, "As shown on your PAN. We'll update your application."],
            ["KEEP_ENTERED_NAME", result.name_entered, "Keep the name you entered. We may need to check a few details."],
          ].map(([value, name, help]) => (
            <label
              key={value}
              className="flex cursor-pointer gap-3 rounded-lg border border-input bg-card px-4 py-3 has-[[data-checked]]:border-primary has-[[data-checked]]:bg-accent"
            >
              <RadioGroupItem value={value!} className="mt-1" />
              <span>
                <span className="block font-medium">{name}</span>
                <span className="text-sm text-muted-foreground">{help}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
        <ErrorNotice message={error} />
        <ActionButton busy={busy} busyLabel="Confirming" onClick={() => verify(choice)}>
          Confirm name
        </ActionButton>
      </StepShell>
    );
  }

  return (
    <StepShell title="Verify your PAN" intro="We check your PAN with a simulated PAN service. Your PAN is masked in our logs.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void verify();
        }}
        className="space-y-4"
        noValidate
      >
        <Field id="pan" label="PAN" hint={FORMAT_HINT} error={formatError}>
          <Input
            id="pan"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={10}
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
            className={`${inputClass} figures uppercase tracking-[0.12em]`}
            {...describe("pan", formatError, FORMAT_HINT)}
          />
        </Field>
        {result && result.status !== "VERIFIED" ? (
          <Notice tone="refer" live>
            {result.message}
          </Notice>
        ) : null}
        {blocked ? (
          <Notice tone="refer" title="We can't continue with this PAN" live>
            {blocked} If it&apos;s yours, verify your phone number again to pick it up from where you left off.
          </Notice>
        ) : null}
        <ErrorNotice message={error} />
        <ActionButton type="submit" busy={busy} busyLabel="Verifying PAN">
          Verify PAN
        </ActionButton>
      </form>
    </StepShell>
  );
}

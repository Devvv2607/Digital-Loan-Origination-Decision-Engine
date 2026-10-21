"use client";

import type { FlowContext } from "../flow";
import { ActionButton, StepShell } from "../ui";

export function ExpiredStep({ ctx }: { ctx: FlowContext }) {
  return (
    <StepShell
      title="This application has expired"
      intro="Applications close after 30 days without activity, and offers close 7 days after they're made. A new application checks your details against today's information."
    >
      <ActionButton onClick={ctx.startOver}>Start a new application</ActionButton>
    </StepShell>
  );
}

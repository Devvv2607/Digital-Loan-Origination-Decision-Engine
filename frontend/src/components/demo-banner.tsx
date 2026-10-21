/** Persistent disclaimer shown at the top of every page (non-negotiable #1). */
export function DemoBanner() {
  return (
    <div role="note" aria-label="Demo disclaimer" className="sticky top-0 z-40 border-b border-[#ecd98f] bg-banner text-foreground">
      <p className="mx-auto w-full max-w-5xl px-4 py-2 text-[0.8125rem] leading-snug">
        <strong className="font-semibold">Demo prototype.</strong> Simulated integrations and synthetic data. Not
        affiliated with any bank or lender.
      </p>
    </div>
  );
}

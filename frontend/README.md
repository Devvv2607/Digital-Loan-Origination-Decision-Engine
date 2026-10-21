# Lendwise (Demo) — Frontend

> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.

Next.js 15 (App Router) + React 19, Tailwind CSS 4, shadcn/ui (Base UI primitives). See `docs/DECISIONS.md` D-35 for why Next 15 rather than 14.

## Run locally

Start the backend first (see `backend/README.md`), then:

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                     # http://localhost:3000
```

Checks: `npm run typecheck`, `npm run lint`, `npm run build`.

## Screens

| Route | What it is |
|---|---|
| `/` | Landing page: what the project is, the 5 one-click demo personas, the journey, what is simulated |
| `/apply` | Applicant journey: phone + OTP, details, PAN, e-KYC, bank-data consent, decision, KFS-style offer, e-sign, disbursal |

## Design notes

- Palette: cool paper `#F6F8FA`, ink `#14213D`, teal actions `#0F6E6E`; approve/refer/decline colours are always paired with an icon and text.
- Type: Public Sans for the interface with tabular figures for money; Source Serif 4 only on the Key Fact Statement, so it reads as a disclosure document.
- The demo disclaimer is sticky at the top of every page.
- Every simulated provider call shows a specific loading label ("Verifying PAN", "Fetching 6 months of bank data").
- The flow asks the backend for `next_step` after each action, so refreshing or returning lands on the right step.
- Accessibility: labelled fields with linked hints and errors, focus moves to each step's heading, visible focus rings, reduced motion respected, colour never the only signal.

## Layout

| Path | Contents |
|---|---|
| `src/app/` | Routes, global theme (`globals.css`), root layout with banner |
| `src/components/landing/` | Persona list, sample decision |
| `src/components/apply/` | Flow orchestrator, progress, shared step UI, one file per step |
| `src/components/ui/` | shadcn/ui components |
| `src/lib/` | API client (one error shape, idempotency keys), session storage, formatting, types |

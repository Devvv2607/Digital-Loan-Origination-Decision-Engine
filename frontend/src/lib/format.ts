const inrFormatter = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/** 1684000 -> "₹16,84,000" */
export function inr(amount: number): string {
  return inrFormatter.format(amount);
}

export function pct(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`;
}

const dateFormatter = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFormatter = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function date(iso: string): string {
  return dateFormatter.format(new Date(iso));
}

export function dateTime(iso: string): string {
  return dateTimeFormatter.format(new Date(iso));
}

export function months(n: number): string {
  return n % 12 === 0 ? `${n / 12} ${n === 12 ? "year" : "years"}` : `${n} months`;
}

export const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
export const PHONE_PATTERN = /^[6-9]\d{9}$/;

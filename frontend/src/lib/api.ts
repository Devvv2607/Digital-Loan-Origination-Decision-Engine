/**
 * Thin client for the Lendwise (Demo) API. Every error is normalised to ApiError with the
 * backend's {error_code, message, details} shape, so screens can show the server's message.
 */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

// ---------------------------------------------------------------- cold start
// The free API host sleeps after about 15 idle minutes and takes up to a minute to wake. Unless
// the server answered in the last AWAKE_MS, a request that takes longer than SLOW_MS shows a
// "waking up" notice (components/server-wake-notice.tsx), and gateway errors or network
// failures are retried for up to WAKE_RETRY_MS: the server was not running, so the request
// was never processed.

const SLOW_MS = 3_000;
const WAKE_RETRY_MS = 90_000;
const WAKING_STATUSES = new Set([502, 503, 504]);

const AWAKE_MS = 10 * 60_000;
let lastAnswer = 0;
const serverAwake = () => lastAnswer > 0 && Date.now() - lastAnswer < AWAKE_MS;
let slowPending = 0;
const wakeListeners = new Set<(waking: boolean) => void>();

function notifyWake() {
  const waking = !serverAwake() && slowPending > 0;
  wakeListeners.forEach((l) => l(waking));
}

/** Subscribe to the "waking up the demo server" state. Returns an unsubscribe function. */
export function onServerWaking(listener: (waking: boolean) => void): () => void {
  wakeListeners.add(listener);
  return () => wakeListeners.delete(listener);
}

let warmUpStarted = false;
/** Fire-and-forget request that starts waking the server as soon as a page loads. */
export function warmUpServer(): void {
  if (warmUpStarted || serverAwake()) return;
  warmUpStarted = true;
  api("/health").catch(() => undefined);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchWakingAware(url: string, init: RequestInit): Promise<Response> {
  const started = Date.now();
  const wasAwake = serverAwake();
  let slow = false;
  const timer = setTimeout(() => {
    if (wasAwake) return;
    slow = true;
    slowPending += 1;
    notifyWake();
  }, SLOW_MS);
  try {
    for (let attempt = 0; ; attempt += 1) {
      try {
        const res = await fetch(url, init);
        if (!wasAwake && WAKING_STATUSES.has(res.status) && Date.now() - started < WAKE_RETRY_MS) {
          await sleep(Math.min(2_000 * 2 ** attempt, 10_000));
          continue;
        }
        if (!WAKING_STATUSES.has(res.status)) lastAnswer = Date.now();
        return res;
      } catch (err) {
        if (wasAwake || Date.now() - started >= WAKE_RETRY_MS) throw err;
        await sleep(Math.min(2_000 * 2 ** attempt, 10_000));
      }
    }
  } finally {
    clearTimeout(timer);
    if (slow) slowPending -= 1;
    notifyWake();
  }
}

const NETWORK_MESSAGE =
  "We couldn't reach the Lendwise demo server. Check your connection and try again in a moment.";

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT";
  body?: unknown;
  token?: string | null;
  idempotencyKey?: string;
  headers?: Record<string, string>;
};

export async function api<T>(path: string, { method = "GET", body, token, idempotencyKey, headers }: Options = {}) {
  const init: RequestInit = {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };
  let res: Response;
  try {
    res = await fetchWakingAware(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", NETWORK_MESSAGE);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data ?? {}) as { error_code?: string; message?: string; details?: Record<string, unknown> };
    throw new ApiError(
      res.status,
      err.error_code ?? "HTTP_ERROR",
      err.message ?? "Something went wrong on our side. Please try again.",
      err.details ?? {},
    );
  }
  return { status: res.status, data: data as T };
}

/** Field-level messages from a VALIDATION_ERROR, keyed by field name. */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError)) return {};
  const fields = (err.details?.fields as { field: string; message: string }[] | undefined) ?? [];
  return Object.fromEntries(fields.map((f) => [f.field, f.message]));
}

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

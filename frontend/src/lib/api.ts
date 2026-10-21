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
    res = await fetch(`${API_URL}${path}`, init);
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

/**
 * Per-tab session for the applicant journey (token, application, persona) plus a per-browser
 * device ID for the velocity check. Storage can be unavailable (private mode), so every access
 * is guarded and the app keeps working without it.
 */

import type { Persona } from "./types";

const KEY = "lendwise.session.v1";
const DEVICE_KEY = "lendwise.device.v1";

export interface Session {
  token: string | null;
  applicationId: string | null;
  persona: Persona | null;
}

const EMPTY: Session = { token: null, applicationId: null, persona: null };

export function loadSession(): Session {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

export function saveSession(session: Session): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    /* storage unavailable: the journey still works for this page view */
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function deviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_KEY);
    if (!id) {
      id = `web-${crypto.randomUUID()}`;
      localStorage.setItem(DEVICE_KEY, id);
    }
    return id;
  } catch {
    return "web-unknown";
  }
}

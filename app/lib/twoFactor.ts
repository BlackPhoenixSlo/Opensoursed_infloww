/**
 * Sign-in's second step (service/account_security_api.py). A password sign-in (or
 * an invite sign-up) whose principal has 2FA on, or whose Agency requires it,
 * answers with a `TwoFactorChallenge` instead of a session cookie. The
 * contexts' `login` / `register` throw it as `TwoFactorRequired`, so callers
 * that only know "signed in or an error" keep working, and the sign-in forms
 * catch it and render `TwoFactorStep`.
 */

import { RelayError } from "@/lib/relay";

export interface TwoFactorChallenge {
  /** "verify": enter a code; "setup": the Agency requires 2FA and this login has none yet. */
  two_factor: "verify" | "setup";
  /** Signed, five minutes; names the principal. */
  ticket: string;
  username: string;
}

export class TwoFactorRequired extends Error {
  challenge: TwoFactorChallenge;
  constructor(challenge: TwoFactorChallenge) {
    super("Two-factor authentication required");
    this.challenge = challenge;
  }
}

export function isTwoFactorChallenge(x: unknown): x is TwoFactorChallenge {
  return typeof x === "object" && x !== null && "two_factor" in x && "ticket" in x;
}

/** A sign-in POST's error as `RelayError`, its message the Relay's words: a
 *  plain `detail`, or a typed one's `message` (`{code, message}`). */
export function authError(status: number, parsed: unknown): RelayError {
  const detail = typeof parsed === "object" && parsed && "detail" in parsed
    ? (parsed as { detail: unknown }).detail
    : undefined;
  const message = typeof detail === "string"
    ? detail
    : typeof detail === "object" && detail && typeof (detail as { message?: unknown }).message === "string"
      ? (detail as { message: string }).message
      : `HTTP ${status}`;
  return new RelayError(status, parsed, message);
}

export type SignedInKind = "user" | "chatter";

/** The sign-in form's one password check, owners then employees
 *  (`POST /auth/sign-in`, service/account_security_api.py). Resolves to the
 *  kind of session the Relay set; throws `TwoFactorRequired` for the code
 *  step, else `authError` (401 wrong password, 403 `account_deactivated`,
 *  429 `too_many_attempts`). */
export async function signIn(username: string, password: string): Promise<SignedInKind> {
  const r = await fetch("/auth/sign-in", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ username, password }),
    credentials: "same-origin",
  });
  const text = await r.text();
  let parsed: unknown = text;
  try { parsed = text ? JSON.parse(text) : null; } catch { /* keep text */ }
  if (!r.ok) throw authError(r.status, parsed);
  if (isTwoFactorChallenge(parsed)) throw new TwoFactorRequired(parsed);
  return (parsed as { kind: SignedInKind }).kind;
}

/** A typed refusal's `code` ("account_deactivated", "too_many_attempts",
 *  "employee_limit", "invalid_code", ...), if `err` is one. */
export function errorCode(err: unknown): string | undefined {
  if (!(err instanceof RelayError)) return undefined;
  const detail = (err.body as { detail?: unknown } | null)?.detail;
  const code = typeof detail === "object" && detail ? (detail as { code?: unknown }).code : undefined;
  return typeof code === "string" ? code : undefined;
}

import { RelayError } from "@/lib/relay";

export interface TwoFactorChallenge {
  two_factor: "verify" | "setup";
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

export async function postAuthJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  const text = await r.text();
  let parsed: unknown = text;
  try { parsed = text ? JSON.parse(text) : null; } catch { }
  if (!r.ok) throw authError(r.status, parsed);
  return parsed as T;
}

export type SignedInKind = "user" | "chatter";

export async function signIn(username: string, password: string): Promise<SignedInKind> {
  const parsed = await postAuthJSON<{ kind: SignedInKind } | TwoFactorChallenge>(
    "/auth/sign-in", { username, password });
  if (isTwoFactorChallenge(parsed)) throw new TwoFactorRequired(parsed);
  return parsed.kind;
}

export function errorCode(err: unknown): string | undefined {
  if (!(err instanceof RelayError)) return undefined;
  const detail = (err.body as { detail?: unknown } | null)?.detail;
  const code = typeof detail === "object" && detail ? (detail as { code?: unknown }).code : undefined;
  return typeof code === "string" ? code : undefined;
}

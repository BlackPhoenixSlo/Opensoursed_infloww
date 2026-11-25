export type FanId = number | string;

export function sameUserId(
  a: FanId | null | undefined,
  b: FanId | null | undefined,
): boolean {
  if (a == null || b == null) return false;
  return String(a) === String(b);
}

export function compareFanIds(a: FanId | null | undefined, b: FanId | null | undefined): number {
  // Ids are opaque, no leading zeros: length-first then lexical equals numeric order; never subtract (strings give NaN).
  const sa = a == null ? "" : String(a);
  const sb = b == null ? "" : String(b);
  if (sa.length !== sb.length) return sa.length - sb.length;
  return sa.localeCompare(sb);
}

export function isValidFanId(v: unknown): v is FanId {
  if (typeof v !== "number" && typeof v !== "string") return false;
  if (typeof v === "number" && !Number.isSafeInteger(v)) return false;
  const s = String(v);
  return /^\d+$/.test(s) && !/^0+$/.test(s);
}

export function fanIdFromParam(param: string | null | undefined): FanId | null {
  const raw = (param ?? "").trim();
  if (!isValidFanId(raw)) return null;
  // Round trip must match: a Fansly snowflake past 2^53 stays a string or it rounds to a ghost id.
  const n = Number(raw);
  return Number.isSafeInteger(n) && String(n) === raw ? n : raw;
}

// The relay's owe-reply badge (unread_total_decide.amber_count) folds this same last-sender rule: change both.
export function lastMessageFromFan(
  chat: { lastMessage?: { fromUser?: { id?: FanId } } | null } | null | undefined,
  accountId: string | null | undefined,
): boolean {
  const from = chat?.lastMessage?.fromUser?.id;
  if (from == null) return false;
  return !sameUserId(from, accountId);
}

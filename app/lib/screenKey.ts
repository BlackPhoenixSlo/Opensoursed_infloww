/**
 * A screen bundle's key and URL (lib/screenBundle.ts, service/screens_api.py), apart from the bundle's runtime so the
 * server half of the inline boot (lib/inlineBoot.server.ts) asks the relay the same URL the browser would: no React here.
 */

export type Screen =
  | { kind: "dashboard"; from: string | null; to: string | null }
  | { kind: "inbox" }
  /** An open thread (service/chat_screen_api.py): its local reads; `lacks` the lists the client has no fresh copy of. */
  | { kind: "chat"; accountId: string; fanId: string; lacks: ChatLack[] };

export type ChatLack = "savedReplies" | "sensitiveWords";

export function screenKey(s: Screen): string {
  if (s.kind === "chat") return `chat|${s.accountId}|${s.fanId}|${s.lacks.join(",")}`;
  return s.kind === "dashboard" ? `dashboard|${s.from ?? ""}|${s.to ?? ""}` : "inbox|0";
}

/** The bundle's URL for `key` (`dashboard|from|to`, `inbox|cursor`, `chat|account|fan|lacks`). */
export function bundlePath(key: string): string {
  const [kind, a, b, c] = key.split("|");
  const qs = new URLSearchParams();
  if (kind === "chat") {
    qs.set("account", a);
    qs.set("fan", b);
    if (c) qs.set("lacks", c);
  } else if (kind === "dashboard") {
    if (a) qs.set("from", a);
    if (b) qs.set("to", b);
  } else {
    qs.set("cursor", a);
  }
  const s = qs.toString();
  return `/admin/screens/${kind}${s ? `?${s}` : ""}`;
}

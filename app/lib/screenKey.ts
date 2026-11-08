/**
 * A screen bundle's key and URL (lib/screenBundle.ts, service/screens_api.py), apart from the bundle's runtime so the
 * server half of the inline boot (lib/inlineBoot.server.ts) asks the relay the same URL the browser would: no React here.
 */

export type Screen =
  | { kind: "dashboard"; from: string | null; to: string | null }
  /** Messages Pro's All Models list at `cursor` (useChatList's offset, the same for every Creator). */
  | { kind: "inbox"; cursor: number }
  /** An open thread (service/chat_screen_api.py): its local reads; `lacks` the lists the client has no fresh copy of. */
  | { kind: "chat"; accountId: string; fanId: string; lacks: ChatLack[] };

export type ChatLack = "savedReplies" | "sensitiveWords";

/** `s`'s identity: two screens with one key share a bundle. */
export function screenKey(s: Screen): string {
  if (s.kind === "chat") return `chat|${s.accountId}|${s.fanId}|${s.lacks.join(",")}`;
  return s.kind === "dashboard" ? `dashboard|${s.from ?? ""}|${s.to ?? ""}` : `inbox|${s.cursor}`;
}

/** `path` with `params` appended to its query. */
export function withQuery(path: string, params: Record<string, string>): string {
  const qs = new URLSearchParams(params).toString();
  return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
}

/** `s`'s bundle URL. */
export function bundlePath(s: Screen): string {
  const qs: Record<string, string> = {};
  if (s.kind === "chat") {
    qs.account = s.accountId;
    qs.fan = s.fanId;
    if (s.lacks.length) qs.lacks = s.lacks.join(",");
  } else if (s.kind === "dashboard") {
    if (s.from) qs.from = s.from;
    if (s.to) qs.to = s.to;
  } else {
    qs.cursor = String(s.cursor);
  }
  return withQuery(`/admin/screens/${s.kind}`, qs);
}

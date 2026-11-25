export type Screen =
  | { kind: "dashboard"; from: string | null; to: string | null }
  | { kind: "inbox"; cursor: number }
  | { kind: "chat"; accountId: string; fanId: string; lacks: ChatLack[] };

export type ChatLack = "savedReplies" | "sensitiveWords";

export function screenKey(s: Screen): string {
  if (s.kind === "chat") return `chat|${s.accountId}|${s.fanId}|${s.lacks.join(",")}`;
  return s.kind === "dashboard" ? `dashboard|${s.from ?? ""}|${s.to ?? ""}` : `inbox|${s.cursor}`;
}

export function withQuery(path: string, params: Record<string, string>): string {
  const qs = new URLSearchParams(params).toString();
  return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
}

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

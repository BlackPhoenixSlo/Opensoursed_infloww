import { relay, type ProxyMeta } from "@/lib/relay";

export type ProxyChoice = { type: "infloww" } | { type: "none" } | { type: "custom"; label: string; ok: boolean | null };

export interface ProxyList {
  proxies: ProxyMeta[];
  pool: { size: number; account_ids: string[]; bad: number };
}

export function currentProxy(list: ProxyList | undefined, accountId: string): ProxyChoice {
  if (list?.pool?.account_ids.includes(accountId)) return { type: "infloww" };
  const bound = list?.proxies.find((p) => p.assigned_account_ids?.includes(accountId));
  return bound ? { type: "custom", label: bound.label, ok: true } : { type: "none" };
}

export async function bindPoolProxy(accountId: string) {
  await relay.post("/admin/proxy-pool/assign", { account_id: accountId });
}

export type ProxyOp =
  | { op: "bindPool" }
  | { op: "unbindPool" }
  | { op: "unbind"; label: string }
  | { op: "assign"; label: string }
  | { op: "reload" };

export function proxyOps(current: ProxyChoice, next: ProxyChoice): ProxyOp[] {
  if (next.type === "infloww") return current.type === "infloww" ? [] : [{ op: "bindPool" }, { op: "reload" }];
  const oldLabel = current.type === "custom" ? current.label : undefined;
  const nextLabel = next.type === "custom" ? next.label : undefined;
  if (current.type === next.type && oldLabel === nextLabel) return [];
  const ops: ProxyOp[] = [];
  if (current.type === "infloww") ops.push({ op: "unbindPool" });
  if (oldLabel) ops.push({ op: "unbind", label: oldLabel });
  if (nextLabel) ops.push({ op: "assign", label: nextLabel });
  ops.push({ op: "reload" });
  return ops;
}

async function runOp(accountId: string, o: ProxyOp) {
  switch (o.op) {
    case "bindPool": return bindPoolProxy(accountId);
    case "unbindPool": return relay.post("/admin/proxy-pool/unbind", { account_id: accountId });
    case "unbind": return relay.post(`/admin/proxies/${encodeURIComponent(o.label)}/unbind`, { account_id: accountId });
    case "assign": return assignProxy(o.label, accountId);
    case "reload": return reloadSession(accountId);
  }
}

export async function assignProxy(label: string, accountId: string) {
  await relay.post("/admin/proxies/assign", { label, account_id: accountId });
}

export function reloadSession(accountId: string) {
  return relay.post(`/admin/reload-session?account_id=${encodeURIComponent(accountId)}`);
}

// A wrong proxy on a Creator can get the account banned: calls run one at a time, in order, a failure stops the rest.
export async function applyProxy(accountId: string, current: ProxyChoice, next: ProxyChoice) {
  for (const o of proxyOps(current, next)) await runOp(accountId, o);
}

export async function attachDefaultProxy(accountId: string): Promise<boolean> {
  const list = await relay.get<ProxyList>("/admin/proxies");
  if (!list.pool?.size || currentProxy(list, accountId).type === "custom") return false;
  await bindPoolProxy(accountId);
  return true;
}

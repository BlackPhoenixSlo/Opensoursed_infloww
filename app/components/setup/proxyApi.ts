/**
 * A Creator's proxy on the relay (re-exported by `creatorFlow.tsx`): what a choice is, and the calls that put an
 * account on it. A wrong proxy on a Creator can get the account banned, so every call and its order matter.
 */

import { relay } from "@/lib/relay";

/** "infloww" is Infloww's own secure proxy (creators0155); ours is the relay's env pool, one proxy picked at random
 *  and kept per account (docs/proxies.md). "none" is the relay's own server IP; "custom" one of your proxies. */
export type ProxyChoice = { type: "infloww" } | { type: "none" } | { type: "custom"; label: string; ok: boolean | null };

/** Puts an account on an Inflowwww proxy: the one it holds, else the least-used (the relay picks). No reload. */
export async function bindPoolProxy(accountId: string) {
  await relay.post("/admin/proxy-pool/assign", { account_id: accountId });
}

/** One relay call of a proxy change, in the order `applyProxy` makes them:
 *   bindPool   → POST /admin/proxy-pool/assign      (the pool proxy it holds, else the least-used)
 *   unbindPool → POST /admin/proxy-pool/unbind
 *   unbind     → POST /admin/proxies/{label}/unbind
 *   assign     → POST /admin/proxies/assign {label}
 *   reload     → POST /admin/reload-session          (the session reconnects through the new proxy) */
export type ProxyOp =
  | { op: "bindPool" }
  | { op: "unbindPool" }
  | { op: "unbind"; label: string }
  | { op: "assign"; label: string }
  | { op: "reload" };

/** The calls that move an account from `current` to `next`, in order; [] when nothing changes. Onto the pool: bind,
 *  then reload (binding moves the account off a custom proxy). Else: off the pool or the old proxy, onto the new one,
 *  then reload. */
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
    case "assign": return relay.post("/admin/proxies/assign", { label: o.label, account_id: accountId });
    case "reload": return relay.post(`/admin/reload-session?account_id=${encodeURIComponent(accountId)}`);
  }
}

/** Applies a proxy choice to an account: `proxyOps`, one call at a time, in order (a failed call stops the rest). */
export async function applyProxy(accountId: string, current: ProxyChoice, next: ProxyChoice) {
  for (const o of proxyOps(current, next)) await runOp(accountId, o);
}

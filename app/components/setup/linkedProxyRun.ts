import { draftProblem, type ProxyDraft } from "./AddProxyModal";
import { buildBody, failedTestText, keepTarget, type Done, type Outcome } from "./linkedProxyForm";
import { assignProxy, bindPoolProxy, currentProxy, reloadSession, type ProxyList } from "./proxyApi";
import { relay } from "@/lib/relay";

const msg = (e: unknown) => (e as Error).message;

export async function reloadNewProxy(accountId: string, done: Done): Promise<Outcome> {
  try {
    await reloadSession(accountId);
    return done;
  } catch (e) {
    return { kind: "reloadFailed", done, error: msg(e) };
  }
}

async function afterFailedAssign(accountId: string, label: string, error: string): Promise<{ assigned: true } | { text: string }> {
  const failed = `Couldn't assign your proxy: ${error}.`;
  const unchanged = (note: string) => ({ text: `${failed} This creator's proxy is unchanged.${note}` });
  let list: ProxyList;
  try {
    list = await relay.get<ProxyList>("/admin/proxies");
  } catch (e) {
    return {
      text: `${failed} Couldn't re-read the proxies (${msg(e)}), so it is unknown whether this creator is on ${label}; check it under Custom proxy.`,
    };
  }
  const ids = list.proxies.find((x) => x.label === label)?.assigned_account_ids;
  if (!ids) return unchanged("");
  if (ids.includes(accountId)) return { assigned: true };
  if (ids.length) return unchanged(` The new proxy ${label} shows as in use by another account, so it was kept.`);
  try {
    await relay.delete(`/admin/proxies/${encodeURIComponent(label)}`);
    return unchanged("");
  } catch (e) {
    return unchanged(` Couldn't remove the new proxy ${label} (${msg(e)}); delete it under Custom proxy.`);
  }
}

// Never unbinds first: the current proxy stays until the new one passed its test and is assigned.
export async function connectNewProxy(accountId: string, draft: ProxyDraft, fallback: boolean): Promise<Outcome> {
  let list: ProxyList;
  try {
    list = await relay.get<ProxyList>("/admin/proxies");
  } catch (e) {
    return { kind: "failed", text: `Couldn't read the proxies: ${msg(e)}` };
  }
  const invalid = draftProblem(draft, list.proxies.map((p) => p.label));
  if (invalid) return { kind: "failed", text: invalid.text };
  const keep = keepTarget(currentProxy(list, accountId), list.pool?.size ?? 0);
  const body = buildBody(draft);
  const path = `/admin/proxies/${encodeURIComponent(body.label)}`;
  try {
    await relay.post("/admin/proxies", body);
  } catch (e) {
    return { kind: "failed", text: `Couldn't add your proxy: ${msg(e)}` };
  }
  let testError: string | null = null;
  try {
    const check = await relay.post<{ ok: boolean; error?: string | null }>(`${path}/test`);
    if (!check.ok) testError = check.error || "it did not reach OnlyFans";
  } catch (e) {
    testError = msg(e);
  }
  if (testError !== null) {
    const cleanupError = await relay.delete(path).then(() => null, msg);
    if (!fallback) return { kind: "failed", text: failedTestText(testError, cleanupError) };
    const kept: Done = { kind: "kept", keep, testError, cleanupError };
    if (!(keep.kind === "pool" && keep.bind)) return kept;
    try {
      await bindPoolProxy(accountId);
    } catch (e) {
      return { kind: "failed", text: `${failedTestText(testError, cleanupError)} The default proxy couldn't be attached either: ${msg(e)}` };
    }
    return reloadNewProxy(accountId, kept);
  }
  try {
    await assignProxy(body.label, accountId);
  } catch (e) {
    const after = await afterFailedAssign(accountId, body.label, msg(e));
    if ("text" in after) return { kind: "failed", text: after.text };
  }
  return reloadNewProxy(accountId, { kind: "connected", label: body.label });
}

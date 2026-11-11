/**
 * linkedProxyRun — the relay calls behind LinkedCreatorProxy's Connect (its state and copy: `linkedProxyForm`).
 *
 * The switch: a fresh `GET /admin/proxies` → create (`POST /admin/proxies`) → test (a failed one is deleted) → assign
 * (`assignProxy`: moves the account off any other proxy in one write) → reload (`reloadSession`). The account is never
 * unbound first, so its current proxy stays until the new one passed its test and is assigned.
 *   - A failed test with the fallback on keeps the creator where it is; an account on none goes on the default pool
 *     when there is one (`bindPoolProxy` + reload, the only fallback write: a failed bind fails the run, a failed
 *     reload after it is `reloadFailed`). Off: it fails with the error.
 *   - A failed assign re-reads the list: the new proxy on this account counts as assigned (reload goes on); on another
 *     account it is kept; on nobody it is deleted. A failed re-read claims nothing about the binding.
 *   - A failed reload keeps the binding; Retry reloads only (`reloadNewProxy`).
 */

import { draftProblem, type ProxyDraft } from "./AddProxyModal";
import { buildBody, failedTestText, keepTarget, type Done, type Outcome } from "./linkedProxyForm";
import { assignProxy, bindPoolProxy, currentProxy, reloadSession, type ProxyList } from "./proxyApi";
import { relay } from "@/lib/relay";

const msg = (e: unknown) => (e as Error).message;

/** Reloads the session through the binding `done` names; a failure keeps the binding (Retry reloads only). */
export async function reloadNewProxy(accountId: string, done: Done): Promise<Outcome> {
  try {
    await reloadSession(accountId);
    return done;
  } catch (e) {
    return { kind: "reloadFailed", done, error: msg(e) };
  }
}

/** After a failed assign, from a fresh read: the new proxy shows on this account (the assign landed: reload), or the
 *  text for the error (deleted only when bound to nobody; kept when another account is on it; a failed re-read says
 *  the binding is unknown). */
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

/** Connect: the switch above, for the typed `draft`, with the fallback box as it was at Connect. */
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

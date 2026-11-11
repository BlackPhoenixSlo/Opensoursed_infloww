"use client";

import { useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { draftProblem, type ProxyDraft } from "./AddProxyModal";
import { useProxyList } from "./creatorFlow";
import {
  INITIAL_LINKED_PROXY, canSubmit, fallbackLabel, keepTarget, linkedProxyReducer, outcomeMessage, type Outcome,
} from "./linkedProxyForm";
import { connectNewProxy, reloadNewProxy } from "./linkedProxyRun";
import { currentProxy } from "./proxyApi";
import { useReportBusy } from "./useReportBusy";
import { IfButton, IfInput, IfLabel, IfNativeSelect } from "@/components/ui/infloww";

/** Optional post-login proxy setup (the switch: `connectNewProxy`). The account's current proxy stays until the new
 *  one passed its test and is assigned. Mount it keyed by the account, so another account starts a fresh form. */
export default function LinkedCreatorProxy({ accountId, onBusy }: { accountId: string; onBusy: (busy: boolean) => void }) {
  const [state, dispatch] = useReducer(linkedProxyReducer, INITIAL_LINKED_PROXY);
  const { draft, open, fallback, busy, outcome } = state;
  const proxies = useProxyList();
  const qc = useQueryClient();
  const taken = proxies.data?.proxies.map((p) => p.label) ?? null;
  const problem = draftProblem(draft, taken);
  const keep = keepTarget(currentProxy(proxies.data, accountId), proxies.data?.pool?.size ?? 0);
  const shown = outcome && outcomeMessage(outcome);

  useReportBusy(busy, onBusy);

  const settle = async (run: Promise<Outcome>) => {
    const result = await run;
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["proxies"] }),
      qc.invalidateQueries({ queryKey: ["accounts"] }),
    ]);
    dispatch({ type: "settled", outcome: result });
  };
  const submit = () => {
    if (!canSubmit(state, taken)) return;
    dispatch({ type: "submitStart" });
    void settle(connectNewProxy(accountId, draft, fallback));
  };
  const retry = () => {
    if (busy || outcome?.kind !== "reloadFailed") return;
    dispatch({ type: "retryStart" });
    void settle(reloadNewProxy(accountId, outcome.done));
  };

  return (
    <div className="space-y-3">
      <button type="button" className="text-sm text-accent hover:text-accent-hover" aria-expanded={open}
        onClick={() => dispatch({ type: "toggle" })} disabled={busy}>
        Click here to add your proxy
      </button>
      {open && (
        <div className="space-y-3 rounded-lg border border-border p-4">
          <fieldset disabled={busy} className="space-y-3">
            <div>
              <IfLabel htmlFor="linked-proxy-type">Type</IfLabel>
              <IfNativeSelect id="linked-proxy-type" value={draft.scheme}
                onChange={(e) => dispatch({ type: "edit", patch: { scheme: e.target.value as ProxyDraft["scheme"] } })}>
                <option value="http">HTTP</option><option value="https">HTTPS</option><option value="socks5">SOCKS5</option>
              </IfNativeSelect>
            </div>
            {([['host', 'IP address or hostname'], ['port', 'Port'], ['username', 'Username (optional)'], ['password', 'Password (optional)']] as const).map(([key, label]) => (
              <div key={key}>
                <IfLabel htmlFor={`linked-proxy-${key}`}>{label}</IfLabel>
                <IfInput id={`linked-proxy-${key}`} value={draft[key]} type={key === "password" ? "password" : "text"}
                  inputMode={key === "port" ? "numeric" : undefined} autoComplete="off" className="w-full"
                  onChange={(e) => dispatch({ type: "edit", patch: { [key]: e.target.value } })} />
              </div>
            ))}
            <label className="flex items-start gap-3 text-sm text-fg">
              <input type="checkbox" checked={fallback} onChange={(e) => dispatch({ type: "setFallback", value: e.target.checked })}
                aria-describedby="proxy-fallback-help" className="mt-1 h-4 w-4 shrink-0 accent-accent" />
              <span>{fallbackLabel(keep)}</span>
            </label>
            <p id="proxy-fallback-help" className="text-sm text-muted">
              This creator&apos;s current proxy stays until yours passes its test and is assigned. Uncheck to keep the
              form open with the error and fix your proxy.
            </p>
            <IfButton onClick={submit} disabled={!canSubmit(state, taken)} title={problem?.text}>
              {busy ? "Checking proxy…" : "Connect proxy"}
            </IfButton>
          </fieldset>
          {proxies.isSuccess && !proxies.data?.pool?.size && <p className="text-sm text-muted">Default proxies are currently unavailable.</p>}
        </div>
      )}
      {shown && (
        <p role={shown.tone === "err" ? "alert" : "status"}
          className={shown.tone === "err" ? "text-sm text-err" : shown.tone === "warn" ? "text-sm text-warn" : "text-sm text-fg"}>
          {shown.text}
        </p>
      )}
      {outcome?.kind === "reloadFailed" && (
        <IfButton onClick={retry} disabled={busy}>{busy ? "Refreshing…" : "Retry session refresh"}</IfButton>
      )}
    </div>
  );
}

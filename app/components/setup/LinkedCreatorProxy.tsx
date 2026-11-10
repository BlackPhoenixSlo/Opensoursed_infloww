"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { EMPTY_DRAFT, draftLabel, draftProblem, type ProxyDraft } from "./AddProxyModal";
import { currentProxy, useProxyList, type ProxyList } from "./creatorFlow";
import { applyProxy, bindPoolProxy } from "./proxyApi";
import { IfButton, IfInput, IfLabel, IfNativeSelect } from "@/components/ui/infloww";
import { BRAND_NAME } from "@/lib/brand";
import { relay } from "@/lib/relay";

/** Optional post-login proxy setup. Test before moving the linked account off its working proxy. */
export default function LinkedCreatorProxy({ accountId, onBusy }: { accountId: string; onBusy: (busy: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ProxyDraft>({ ...EMPTY_DRAFT, scheme: "http" });
  const [message, setMessage] = useState("");
  const [fallback, setFallback] = useState(true);
  const proxies = useProxyList();
  const qc = useQueryClient();
  const problem = draftProblem(draft, proxies.data?.proxies.map((p) => p.label) ?? null);
  const change = useMutation({
    mutationFn: async () => {
      const list = await relay.get<ProxyList>("/admin/proxies");
      const invalid = draftProblem(draft, list.proxies.map((p) => p.label));
      if (invalid) throw new Error(invalid.text);
      const label = draftLabel(draft).trim();
      try {
        await relay.post("/admin/proxies", {
          label, scheme: draft.scheme, host: draft.host.trim(), port: Number(draft.port),
          username: draft.username.trim() || null, password: draft.password || null,
        });
        const path = `/admin/proxies/${encodeURIComponent(label)}`;
        try {
          const check = await relay.post<{ ok: boolean }>(`${path}/test`);
          if (!check.ok) throw new Error("Proxy check failed. Check your details or switch to the default proxies.");
        } catch (error) {
          await relay.delete(path).catch(() => undefined);
          throw error;
        }
        await applyProxy(accountId, currentProxy(list, accountId), { type: "custom", label, ok: true });
        return false;
      } catch (error) {
        if (!fallback) throw error;
        // Reload even if an earlier attempt already bound the default proxy.
        await bindPoolProxy(accountId);
        await relay.post(`/admin/reload-session?account_id=${encodeURIComponent(accountId)}`);
        return true;
      }
    },
    onSuccess: (usedFallback) => {
      setDraft({ ...EMPTY_DRAFT, scheme: "http" });
      setMessage(usedFallback ? `Your proxy could not connect. This creator is now using ${BRAND_NAME}'s default proxy.` : "Your proxy is connected.");
    },
    onSettled: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["proxies"] }),
        qc.invalidateQueries({ queryKey: ["accounts"] }),
      ]);
      onBusy(false);
    },
  });
  const submit = () => {
    if (change.isPending) return;
    setMessage(""); onBusy(true); change.mutate();
  };
  return (
    <div className="space-y-3">
      <button type="button" className="text-sm text-accent hover:text-accent-hover" aria-expanded={open}
        onClick={() => setOpen(!open)} disabled={change.isPending}>
        Click here to add your proxy
      </button>
      {open && (
        <div className="space-y-3 rounded-lg border border-border p-4">
          <fieldset disabled={change.isPending} className="space-y-3">
            <div>
              <IfLabel htmlFor="linked-proxy-type">Type</IfLabel>
              <IfNativeSelect id="linked-proxy-type" value={draft.scheme} onChange={(e) => setDraft({ ...draft, scheme: e.target.value as ProxyDraft["scheme"] })}>
                <option value="http">HTTP</option><option value="https">HTTPS</option><option value="socks5">SOCKS5</option>
              </IfNativeSelect>
            </div>
            {([['host', 'IP address or hostname'], ['port', 'Port'], ['username', 'Username (optional)'], ['password', 'Password (optional)']] as const).map(([key, label]) => (
              <div key={key}>
                <IfLabel htmlFor={`linked-proxy-${key}`}>{label}</IfLabel>
                <IfInput id={`linked-proxy-${key}`} value={draft[key]} type={key === "password" ? "password" : "text"}
                  inputMode={key === "port" ? "numeric" : undefined} autoComplete="off" className="w-full"
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
              </div>
            ))}
            <label className="flex items-start gap-3 text-sm text-fg">
              <input type="checkbox" checked={fallback} onChange={(e) => setFallback(e.target.checked)}
                aria-describedby="proxy-fallback-help" className="mt-1 h-4 w-4 shrink-0 accent-accent" />
              <span>Use {BRAND_NAME}&apos;s default proxy if mine fails</span>
            </label>
            <p id="proxy-fallback-help" className="text-sm text-muted">
              If your proxy cannot connect during setup, we&apos;ll automatically assign a {BRAND_NAME} proxy instead.
              No extra proxy details needed. Uncheck to keep the error visible and fix your own proxy.
            </p>
            <IfButton onClick={() => submit()} disabled={!!problem || change.isPending} title={problem?.text}>
              {change.isPending ? "Checking proxy…" : "Connect proxy"}
            </IfButton>
          </fieldset>
          {change.isError && <p role="alert" className="text-sm text-err">Couldn&apos;t connect the proxy{fallback ? " or the default proxy" : ""}. Check your details and try again.</p>}
          {message && <p role="status" className="text-sm text-fg">{message}</p>}
          {proxies.isSuccess && !proxies.data?.pool?.size && <p className="text-sm text-muted">Default proxies are currently unavailable.</p>}
        </div>
      )}
    </div>
  );
}

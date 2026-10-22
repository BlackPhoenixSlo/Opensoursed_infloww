"use client";

/**
 * BrowserbaseLoginCard — "Try Browserbase login" (backend: service/remote_login.py).
 *
 * The operator types the creator's OnlyFans email + password and picks a proxy. POST /admin/login/remote/start
 * (backend "browserbase") opens a Browserbase Chromium on Browserbase's own network (its managed proxies) and fills in
 * OnlyFans' login form. When OnlyFans shows a Cloudflare / captcha / 2FA check, the operator solves it in Browserbase's
 * live view (embedded below while the job runs); nothing solves it automatically. On success the relay saves the
 * session through the paste-curl pipeline and attaches the chosen proxy to the account for all later traffic, so this
 * card only reports and hands the account on.
 *
 * The password is sent once and cleared from state; the polled status carries no secrets. While the job runs the form
 * is replaced by its progress and the live view. Any failure ends the job with the error shown here.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { relay, RelayError } from "@/lib/relay";
import { Button, Card, Input } from "@/components/ui/primitives";
import { useProxyList } from "@/components/setup/creatorFlow";

export interface RemoteLoginStatus {
  id: string;
  backend: string;
  state: "starting" | "typing" | "challenge" | "otp" | "capturing" | "done" | "error" | "cancelled";
  message: string;
  error: string | null;
  account_id: string | null;
  session_file: string | null;
  proxy_label: string;
  live_view_url: string | null;
  expires_at: number;
}

const TERMINAL = new Set(["done", "error", "cancelled"]);
/** What each running state asks of the operator. */
const STATE_TEXT: Record<string, string> = {
  starting: "Starting the remote browser (about 10 to 20 seconds)…",
  typing: "Entering the email and password on OnlyFans…",
  challenge: "OnlyFans is showing a verification check. Solve it in the live view.",
  otp: "OnlyFans is asking for the 2FA code. Type it in the live view.",
  capturing: "Signed in. Saving the session…",
};
const jobPath = (id: string) => `/admin/login/remote/${encodeURIComponent(id)}`;

export default function BrowserbaseLoginCard({ onLinked, initialNickname = "", initialProxyLabel = "" }: {
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  initialProxyLabel?: string;
}) {
  const qc = useQueryClient();
  const proxiesQ = useProxyList();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [proxyLabel, setProxyLabel] = useState(initialProxyLabel);
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const linkedRef = useRef<string | null>(null);
  const liveRef = useRef<HTMLDivElement | null>(null);

  const startM = useMutation<RemoteLoginStatus, RelayError, void>({
    mutationFn: () =>
      relay.post<RemoteLoginStatus>("/admin/login/remote/start", {
        email: email.trim(), password, proxy_label: proxyLabel, backend: "browserbase",
        nickname: initialNickname.trim() || undefined,
      }),
    onSuccess: (job) => {
      setErr(null);
      setPassword("");
      setJobId(job.id);
    },
    onError: (e) => setErr(`Couldn't start the login: ${e.message}`),
  });

  const statusQ = useQuery<RemoteLoginStatus>({
    queryKey: ["remote-login", jobId],
    queryFn: () => relay.get<RemoteLoginStatus>(jobPath(jobId!)),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.state) ? false : 1500),
  });
  const status = statusQ.data;
  const running = !!jobId && !(status && TERMINAL.has(status.state));

  const done = status?.state === "done" && !!status.account_id;
  useEffect(() => {
    if (!done || linkedRef.current === status!.id) return;
    linkedRef.current = status!.id;
    for (const key of ["accounts", "proxies", "drift", "health-all"]) qc.invalidateQueries({ queryKey: [key] });
    onLinked?.(status!.account_id!);
  }, [done, status, qc, onLinked]);

  const liveUrl = running ? status?.live_view_url ?? null : null;
  useEffect(() => {
    if (liveUrl) liveRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [liveUrl]);

  const cancel = () => { if (jobId) relay.post(`${jobPath(jobId)}/cancel`).catch(() => {}); };

  const canStart = email.trim() !== "" && password !== "" && proxyLabel !== "" && !startM.isPending && !running;
  const proxies = proxiesQ.data?.proxies ?? [];

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-base font-semibold mb-1">Try Browserbase login</h2>
        <p className="text-sm text-fg-dim leading-relaxed">
          The login runs in a remote browser on Browserbase&apos;s network. The proxy you choose is attached to the
          account for all later traffic. If OnlyFans shows a verification check or asks for a 2FA code, you solve
          it yourself in the live view that opens here.
        </p>
      </div>

      {!running && !done && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label htmlFor="bb-email" className="block text-xs text-fg-dim mb-1">OnlyFans email</label>
              <Input id="bb-email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" placeholder="creator@example.com" />
            </div>
            <div>
              <label htmlFor="bb-password" className="block text-xs text-fg-dim mb-1">OnlyFans password</label>
              <Input id="bb-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <p className="md:col-span-2 -mt-1 text-[11px] text-fg-dim">The password is sent once to start the login and is never stored.</p>
          </div>

          <div>
            <label htmlFor="bb-proxy" className="block text-xs text-fg-dim mb-1">Proxy (required; attached to the account for all later traffic)</label>
            <select
              id="bb-proxy"
              aria-label="Browserbase proxy"
              value={proxyLabel}
              onChange={(e) => setProxyLabel(e.target.value)}
              disabled={proxiesQ.isSuccess && proxies.length === 0}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent disabled:opacity-60"
            >
              <option value="">{proxiesQ.isSuccess && proxies.length === 0 ? "No proxies yet" : "— choose a proxy —"}</option>
              {proxies.map((p) => (
                <option key={p.label} value={p.label}>{p.label} · {p.host}:{p.port}</option>
              ))}
            </select>
            {proxiesQ.isSuccess && proxies.length === 0 && (
              <p className="text-[11px] text-fg-dim mt-1">Add one first: go back to Proxy selection and choose Custom proxy → New proxy.</p>
            )}
          </div>

          {err && <div role="alert" className="text-err text-sm whitespace-pre-wrap">{err}</div>}
          {status?.state === "error" && <div role="alert" className="text-err text-sm whitespace-pre-wrap">Login failed: {status.error}</div>}
          {status?.state === "cancelled" && <div className="text-fg-dim text-sm">Login cancelled.</div>}

          <Button type="button" disabled={!canStart} onClick={() => startM.mutate()}>
            {startM.isPending ? "Starting browser…" : status && TERMINAL.has(status.state) ? "Try again" : "Try Browserbase login"}
          </Button>
        </>
      )}

      {running && status && (
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <p className="text-fg">{STATE_TEXT[status.state] ?? status.message}</p>
            <Button type="button" variant="secondary" size="sm" onClick={cancel}>Cancel</Button>
          </div>
          {liveUrl ? (
            <div ref={liveRef} className="space-y-2">
              <a href={liveUrl} target="_blank" rel="noopener noreferrer" className="inline-block text-sm text-cta hover:underline">
                Open the live view full size in a new tab ↗
              </a>
              <iframe
                title="Browserbase live view"
                src={liveUrl}
                sandbox="allow-same-origin allow-scripts"
                allow="clipboard-read; clipboard-write"
                className="w-full aspect-[16/10] border border-border rounded-lg bg-bg-elev-1"
              />
            </div>
          ) : (
            <p className="text-xs text-fg-dim">The live view appears here once the browser is up.</p>
          )}
        </div>
      )}

      {done && status && (
        <div className="space-y-3 text-sm">
          <p className="text-ok">
            Account {status.account_id} added. Proxy {status.proxy_label} is attached for all later traffic.
          </p>
        </div>
      )}
    </Card>
  );
}

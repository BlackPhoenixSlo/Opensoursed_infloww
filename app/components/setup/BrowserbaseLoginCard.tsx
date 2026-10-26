"use client";

/**
 * BrowserbaseLoginCard — "Try Browserbase login" (backend: service/remote_login.py).
 *
 * The operator types the creator's OnlyFans email + password. POST /admin/login/remote/start (backend "browserbase")
 * opens a Browserbase Chromium on Browserbase's own network (its managed proxies) and fills in OnlyFans' login form.
 * When OnlyFans shows a Cloudflare / captcha check, the operator solves it in Browserbase's live view (embedded below
 * while the job runs, and one tap away full screen); nothing solves it automatically. When OnlyFans asks for the 2FA
 * code, the card shows a code field: POST /admin/login/remote/{id}/otp hands it to the job, which types it into
 * OnlyFans' own field; a code OnlyFans does not take (within the relay's wait) comes back as rejected and the field asks again. The live
 * view stays up as the fallback (the code can be typed there too). No extension is needed, so
 * this is how a creator is linked from a phone. The proxy is the Add creator flow's Proxy selection (`proxy`, the
 * Inflowwww proxy by default): the card has no proxy picker of its own. On success the relay saves the session through
 * the paste-curl pipeline and binds that proxy to the account for all later traffic, so this card only reports and
 * hands the account on.
 *
 * The password is sent once and cleared from state; the polled status carries no secrets. While the job runs the form
 * is replaced by its progress and the live view. Any failure ends the job with the error shown here.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { relay, RelayError } from "@/lib/relay";
import { Button, Card, Input } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { proxyText, useProxyList, type ProxyChoice } from "@/components/setup/creatorFlow";
import { BRAND_NAME } from "@/lib/brand";

export interface RemoteLoginStatus {
  id: string;
  backend: string;
  state: "starting" | "typing" | "challenge" | "otp" | "capturing" | "done" | "error" | "cancelled";
  message: string;
  error: string | null;
  account_id: string | null;
  session_file: string | null;
  /** The Proxy selection bound after the login; `proxy_label` names a custom one ("" otherwise). */
  proxy: ProxyChoice["type"];
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
  otp: "OnlyFans is asking for the 2FA code. Enter it below (or in the live view).",
  capturing: "Signed in. Saving the session…",
};
const jobPath = (id: string) => `/admin/login/remote/${encodeURIComponent(id)}`;
/** The relay's messages while the job is on OnlyFans' 2FA prompt (remote_login.OTP_CHECKING / OTP_REJECTED /
 * OTP_NOT_TYPED; the last two matched by prefix). */
const OTP_CHECKING = "checking the 2FA code";
const OTP_REJECTED = "OnlyFans didn't accept that code";
const OTP_NOT_TYPED = "couldn't type the 2FA code";
const OTP_CODE = /^\d{6,8}$/;
/** What the code field keeps of what was typed or pasted: spaces and dashes dropped ("123 456", "1234-5678"), nothing
 *  else changed or cut, so a mistyped or overlong code stays visibly wrong (Submit off) instead of becoming another code. */
const otpInput = (raw: string) => raw.replace(/[\s-]/g, "");

/** What a finished job left the account on. */
function attachedText(s: RemoteLoginStatus) {
  if (s.proxy === "infloww") return `The ${BRAND_NAME} proxy is attached for all later traffic.`;
  if (s.proxy === "custom") return `Proxy ${s.proxy_label} is attached for all later traffic.`;
  return "No proxy was attached.";
}

export default function BrowserbaseLoginCard({ onLinked, initialNickname = "", proxy }: {
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  /** The flow's Proxy selection, bound to the account after the login. None (a row's re-login): nothing is bound, so
   *  the account keeps the proxy it is on. */
  proxy?: ProxyChoice;
}) {
  const qc = useQueryClient();
  const proxiesQ = useProxyList();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [howOpen, setHowOpen] = useState(false);
  const [otp, setOtp] = useState("");
  const [otpErr, setOtpErr] = useState<string | null>(null);
  const linkedRef = useRef<string | null>(null);
  const liveRef = useRef<HTMLDivElement | null>(null);

  const startM = useMutation<RemoteLoginStatus, RelayError, void>({
    mutationFn: () =>
      relay.post<RemoteLoginStatus>("/admin/login/remote/start", {
        email: email.trim(), password, backend: "browserbase",
        proxy: proxy?.type ?? "none", proxy_label: proxy?.type === "custom" ? proxy.label : undefined,
        nickname: initialNickname.trim() || undefined,
      }),
    onSuccess: (job) => {
      setErr(null);
      setPassword("");
      setOtp("");
      setOtpErr(null);
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

  const otpM = useMutation<RemoteLoginStatus, RelayError, string>({
    mutationFn: (code) => relay.post<RemoteLoginStatus>(`${jobPath(jobId!)}/otp`, { code }),
    onSuccess: async (job, sent) => {
      setOtpErr(null);
      setOtp((cur) => (cur === sent ? "" : cur));
      // A poll still in flight was read before the code was in: it must not land after this and unlock the field.
      const key = ["remote-login", job.id];
      await qc.cancelQueries({ queryKey: key });
      const cached = qc.getQueryData<RemoteLoginStatus>(key);
      if (!cached || cached.state === "otp") qc.setQueryData(key, job); // a newer poll already past the prompt wins
    },
    onError: (e) => setOtpErr(`Couldn't send the code: ${e.message}`),
  });
  const onOtp = status?.state === "otp";
  const [wasOnOtp, setWasOnOtp] = useState(onOtp);
  if (wasOnOtp !== onOtp) { // left (or reached) the 2FA prompt: no stale digits or error
    setWasOnOtp(onOtp);
    setOtp("");
    setOtpErr(null);
  }
  const otpChecking = onOtp && status.message === OTP_CHECKING;
  const otpRejected = onOtp && status.message.startsWith(OTP_REJECTED);
  const otpNotTyped = onOtp && status.message.startsWith(OTP_NOT_TYPED);
  const otpLocked = otpM.isPending || otpChecking; // in flight, or OnlyFans is checking it

  const cancel = () => { if (jobId) relay.post(`${jobPath(jobId)}/cancel`).catch(() => {}); };

  const canStart = email.trim() !== "" && password !== "" && !startM.isPending && !running;

  return (
    // On a phone the card is the modal step's whole content: no second frame inside the modal's, so the form and the
    // live view get the full width.
    <Card className="space-y-4 max-md:border-0 max-md:bg-transparent max-md:p-0">
      <div>
        <h2 className="text-base font-semibold mb-1">Try Browserbase login</h2>
        {/* On a phone the explanation folds behind "How it works", so the email, password and start button fit on the
            first screen. */}
        {!running && (
          <>
            <button
              type="button" aria-expanded={howOpen} onClick={() => setHowOpen((o) => !o)}
              className="md:hidden text-sm text-cta hover:underline"
            >
              How it works
            </button>
            <p className={cn("text-sm text-fg-dim leading-relaxed", !howOpen && "max-md:hidden")}>
              The login runs in a remote browser on Browserbase&apos;s network, so no extension is needed and it works on a
              phone. If OnlyFans shows a verification check, you solve it yourself in the live view; a 2FA code you enter here.
            </p>
          </>
        )}
        <p className="mt-2 text-sm">
          <span className="text-fg-dim">Proxy for this account: </span>{proxy ? proxyText(proxy, proxiesQ.data) : "unchanged (the one it is on now)"}
        </p>
      </div>

      {!running && !done && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label htmlFor="bb-email" className="block text-xs text-fg-dim mb-1">OnlyFans email</label>
              <Input
                id="bb-email" type="email" inputMode="email" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" placeholder="creator@example.com"
              />
            </div>
            <div>
              <label htmlFor="bb-password" className="block text-xs text-fg-dim mb-1">OnlyFans password</label>
              <Input id="bb-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <p className="md:col-span-2 -mt-1 text-[11px] text-fg-dim">The password is sent once to start the login and is never stored.</p>
          </div>

          {err && <div role="alert" className="text-err text-sm whitespace-pre-wrap">{err}</div>}
          {status?.state === "error" && <div role="alert" className="text-err text-sm whitespace-pre-wrap">Login failed: {status.error}</div>}
          {status?.state === "cancelled" && <div className="text-fg-dim text-sm">Login cancelled.</div>}

          <Button type="button" disabled={!canStart} onClick={() => startM.mutate()} className="w-full md:w-auto">
            {startM.isPending ? "Starting browser…" : status && TERMINAL.has(status.state) ? "Try again" : "Try Browserbase login"}
          </Button>
        </>
      )}

      {running && status && (
        <div className="space-y-3 text-sm">
          <div className="flex items-start justify-between gap-3">
            <p role="status" className="text-fg">{STATE_TEXT[status.state] ?? status.message}</p>
            <Button type="button" variant="secondary" size="sm" onClick={cancel} className="shrink-0">Stop login</Button>
          </div>
          {status.state === "otp" && (
            <form
              className="space-y-2"
              onSubmit={(e) => { e.preventDefault(); if (OTP_CODE.test(otp) && !otpLocked) otpM.mutate(otp); }}
            >
              <label htmlFor="bb-otp" className="block text-xs text-fg-dim">2FA code</label>
              <div className="flex gap-2">
                <Input
                  id="bb-otp" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*"
                  minLength={6} autoFocus value={otp} placeholder="123456" className="max-w-40"
                  disabled={otpLocked}
                  onChange={(e) => setOtp(otpInput(e.target.value))}
                />
                <Button type="submit" disabled={!OTP_CODE.test(otp) || otpLocked}>
                  {otpM.isPending ? "Sending…" : "Submit code"}
                </Button>
              </div>
              {otpChecking && <p className="text-xs text-fg-dim">Checking the code with OnlyFans…</p>}
              {otpRejected && (
                <div role="alert" className="text-err text-sm">
                  OnlyFans didn&apos;t accept that code (or hasn&apos;t answered yet). Check it and try again.
                </div>
              )}
              {otpNotTyped && (
                <div role="alert" className="text-err text-sm">
                  The code couldn&apos;t be typed into OnlyFans. Try again, or type it in the live view.
                </div>
              )}
              {otpErr && <div role="alert" className="text-err text-sm whitespace-pre-wrap">{otpErr}</div>}
            </form>
          )}
          {liveUrl ? (
            <div ref={liveRef} className="space-y-2">
              {/* Touch inside an iframe is awkward on a phone: the full-screen page is one tap away. */}
              <a
                href={liveUrl} target="_blank" rel="noopener noreferrer"
                className="flex w-full items-center justify-center gap-1 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover md:inline-flex md:w-auto md:py-2"
              >
                Open live view full screen ↗
              </a>
              <iframe
                title="Browserbase live view"
                src={liveUrl}
                sandbox="allow-same-origin allow-scripts"
                allow="clipboard-read; clipboard-write"
                className="block w-full max-w-full aspect-[4/3] md:aspect-[16/10] border border-border rounded-lg bg-bg-elev-1"
              />
              <p className="text-[11px] text-fg-dim">After solving it full screen, come back to this tab: the login finishes here.</p>
            </div>
          ) : (
            <p className="text-xs text-fg-dim">The live view appears here once the browser is up.</p>
          )}
        </div>
      )}

      {done && status && (
        <div className="space-y-3 text-sm">
          <p className="text-ok">Account {status.account_id} added. {attachedText(status)}</p>
        </div>
      )}
    </Card>
  );
}

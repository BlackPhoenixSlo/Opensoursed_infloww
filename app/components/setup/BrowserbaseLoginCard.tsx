"use client";

/**
 * BrowserbaseLoginCard — the Add creator flow's Browser login (backend: service/remote_login.py).
 *
 * The operator types the creator's OnlyFans email + password. POST /admin/login/remote/start (backend "browserbase")
 * opens a Browserbase Chromium on Browserbase's own network (its managed proxies) and fills in OnlyFans' login form.
 * When OnlyFans shows a Cloudflare / captcha check, the operator solves it in Browserbase's live view (embedded below
 * while the job runs, and one tap away full screen); nothing solves it automatically. When OnlyFans asks for the 2FA
 * code, the card shows a code field: POST /admin/login/remote/{id}/otp hands it to the job, which types it into
 * OnlyFans' own field; a code OnlyFans does not take (within the relay's wait) comes back as rejected and the field asks again. The live
 * view stays up as the fallback (the code can be typed there too). No extension is needed, so
 * this is how a creator is linked from a phone. The proxy is automatic: a new login sends no proxy choice, so the
 * relay binds its own (the Inflowwww proxy pool's tier-aware pick when it has one, else none); a row's re-login
 * (`keepProxy`) sends "none", which binds nothing, so the account keeps the proxy it is on. On success the relay saves
 * the session through the paste-curl pipeline and binds that proxy, so this card only reports and hands the account on.
 *
 * Inside the modal (`IfModal footerSlot`) its start button sits in the modal's footer (EditorFooter), only while
 * `active` (the other sign-in shown: the card stays mounted, so a running job still links).
 *
 * The password is sent once and cleared from state; the polled status carries no secrets. While the job runs the form
 * is replaced by its progress and the live view. Any failure ends the job with the error shown here.
 */

import { accountSessionCaptured } from "@/lib/accountSession";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { relay, RelayError } from "@/lib/relay";
import { EditorFooter } from "@/components/ui/ifModal";
import { IfButton, IfHelp, IfInput, IfLabel } from "@/components/ui/infloww";
import type { ProxyChoice } from "@/components/setup/creatorFlow";
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
/** The email + password form: the footer's start button submits it. */
const BB_FORM_ID = "browser-login-form";
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

export default function BrowserbaseLoginCard({ onLinked, initialNickname = "", keepProxy = false, active = true }: {
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  /** A row's re-login: bind nothing, so the account keeps the proxy it is on. Else the relay's automatic proxy. */
  keepProxy?: boolean;
  /** Shown (the start button in the footer); false while the other sign-in is. */
  active?: boolean;
}) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [otpErr, setOtpErr] = useState<string | null>(null);
  const linkedRef = useRef<string | null>(null);
  const liveRef = useRef<HTMLDivElement | null>(null);

  const startM = useMutation<RemoteLoginStatus, RelayError, void>({
    mutationFn: () =>
      relay.post<RemoteLoginStatus>("/admin/login/remote/start", {
        email: email.trim(), password, backend: "browserbase",
        // No choice: the relay's default (its proxy pool when it has one, else none).
        proxy: keepProxy ? "none" : undefined,
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
    // eslint-disable-next-line local/no-fixed-polling -- remote-login job has no SSE event; stops when the job ends
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.state) ? false : 1500),
  });
  const status = statusQ.data;
  const running = !!jobId && !(status && TERMINAL.has(status.state));

  const done = status?.state === "done" && !!status.account_id;
  useEffect(() => {
    if (!done || linkedRef.current === status!.id) return;
    linkedRef.current = status!.id;
    accountSessionCaptured(status!.account_id!);
    for (const key of ["accounts", "proxies", "health-all"]) qc.invalidateQueries({ queryKey: [key] });
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

  const startLabel = startM.isPending ? "Starting browser…" : status && TERMINAL.has(status.state) ? "Try again" : "Start browser login";

  return (
    <div className="space-y-4">
      <IfHelp className="mt-0 text-[14px] leading-[22px]">
        {keepProxy ? "Keeps its current proxy." : "Proxy assigned automatically. You can assign yours later."}
      </IfHelp>

      {!running && !done && (
        <form
          id={BB_FORM_ID} className="space-y-4"
          onSubmit={(e) => { e.preventDefault(); if (canStart) startM.mutate(); }}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <IfLabel htmlFor="bb-email">OnlyFans email</IfLabel>
              <IfInput
                id="bb-email" type="email" inputMode="email" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" placeholder="creator@example.com"
                className="w-full"
              />
            </div>
            <div>
              <IfLabel htmlFor="bb-password">OnlyFans password</IfLabel>
              <IfInput
                id="bb-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password" className="w-full"
              />
            </div>
            <IfHelp className="-mt-2 md:col-span-2">The password is sent once to start the login and is never stored.</IfHelp>
          </div>

          {err && <div role="alert" className="text-err text-sm whitespace-pre-wrap">{err}</div>}
          {status?.state === "error" && <div role="alert" className="text-err text-sm whitespace-pre-wrap">Login failed: {status.error}</div>}
          {status?.state === "cancelled" && <div className="text-muted text-sm">Login cancelled.</div>}

          {active && (
            <EditorFooter>
              <IfButton type="submit" form={BB_FORM_ID} variant="primary" disabled={!canStart}>{startLabel}</IfButton>
            </EditorFooter>
          )}
        </form>
      )}

      {running && status && (
        <div className="space-y-3 text-sm">
          <div className="flex items-start justify-between gap-3">
            <p role="status" className="text-fg">{STATE_TEXT[status.state] ?? status.message}</p>
            <IfButton onClick={cancel}>Stop login</IfButton>
          </div>
          {status.state === "otp" && (
            <form
              className="space-y-2"
              onSubmit={(e) => { e.preventDefault(); if (OTP_CODE.test(otp) && !otpLocked) otpM.mutate(otp); }}
            >
              <IfLabel htmlFor="bb-otp" className="mb-0">2FA code</IfLabel>
              <div className="flex gap-2">
                <IfInput
                  id="bb-otp" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*"
                  minLength={6} autoFocus value={otp} placeholder="123456" className="w-40"
                  disabled={otpLocked}
                  onChange={(e) => setOtp(otpInput(e.target.value))}
                />
                <IfButton type="submit" variant="primary" disabled={!OTP_CODE.test(otp) || otpLocked}>
                  {otpM.isPending ? "Sending…" : "Submit code"}
                </IfButton>
              </div>
              {otpChecking && <p className="text-xs text-muted">Checking the code with OnlyFans…</p>}
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
                className="flex h-8 w-full items-center justify-center rounded-md border border-border px-[15px] text-[14px] text-fg hover:border-accent hover:text-accent md:inline-flex md:w-auto"
              >
                Open live view full screen
              </a>
              <iframe
                title="Browserbase live view"
                src={liveUrl}
                sandbox="allow-same-origin allow-scripts"
                allow="clipboard-read; clipboard-write"
                className="block w-full max-w-full aspect-[4/3] md:aspect-[16/10] border border-border rounded-lg bg-bg-elev-1"
              />
              <p className="text-[12px] text-muted">After solving it full screen, come back to this tab: the login finishes here.</p>
            </div>
          ) : (
            <p className="text-xs text-muted">The live view appears here once the browser is up.</p>
          )}
        </div>
      )}

      {done && status && (
        <div className="space-y-3 text-sm">
          <p className="text-ok">Account {status.account_id} added. {attachedText(status)}</p>
        </div>
      )}
    </div>
  );
}

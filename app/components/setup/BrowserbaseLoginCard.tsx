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
 * relay binds its own default (the Inflowwww proxy pool's tier-aware pick when it has one, else none) unless the
 * account is already on a proxy, which it keeps; a row's re-login (`keepProxy`) sends "none", which binds nothing.
 * On success the relay saves the session through the paste-curl pipeline and binds that proxy, so this card only
 * reports (the job names the proxy the account ended on) and hands the account on.
 *
 * Inside the modal (`IfModal footerSlot`) its start button sits in the modal's footer (EditorFooter), only while
 * `active` (the other sign-in shown: the card stays mounted, so a running job still links).
 *
 * The password is sent once and cleared from state; the polled status carries no secrets. While the job runs the form
 * is replaced by its progress and the live view, and `onBusy` hears it (useReportBusy). Any failure ends the job with the error
 * shown here; a job the relay no longer knows (404: it restarted, or the job expired) ends as "lost". A status read
 * that fails otherwise (5xx, network) shows its error under Stop login and the poll goes on; failing for
 * POLL_GIVE_UP_MS straight it stops, and the card says so with Stop login and Try again (polls again). The card is never
 * blank while a job runs, also before its first status.
 *
 * Unmounting the card (the modal closed, Back, the other sign-in linking) stops a job that is still running, also one
 * whose start answers after the unmount: nothing else could stop it, and it would still link and bind an account.
 */

import { accountSessionCaptured } from "@/lib/accountSession";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { relay, RelayError } from "@/lib/relay";
import { EditorFooter } from "@/components/ui/ifModal";
import { IfButton, IfHelp, IfInput, IfLabel } from "@/components/ui/infloww";
import {
  jobPath, STATE_TEXT, TERMINAL, type RemoteLoginStatus,
} from "@/components/setup/remoteLogin";
import { OtpCodeForm } from "@/components/setup/RemoteLoginOtp";
import { useReportBusy } from "@/components/setup/useReportBusy";
import { BRAND_NAME } from "@/lib/brand";

export type { RemoteLoginStatus };

/** The email + password form: the footer's start button submits it. */
const BB_FORM_ID = "browser-login-form";

/** The status poll's 404: the relay no longer has the job. */
const LOST = "the relay lost this login (it restarted, or the login expired). Try again.";
const isLost = (e: unknown) => e instanceof RelayError && e.status === 404;
/** How long status reads may fail in a row (not 404) before the poll stops. */
export const POLL_GIVE_UP_MS = 30_000;
/** The poll's last error once it gave up (its message is the last read's). */
class PollGaveUp extends Error {}
const gaveUp = (e: unknown) => e instanceof PollGaveUp;

/** What a finished job left the account on. */
function attachedText(s: RemoteLoginStatus) {
  if (s.proxy === "infloww") return `The ${BRAND_NAME} proxy is attached for all later traffic.`;
  if (s.proxy === "custom") return `Proxy ${s.proxy_label} is attached for all later traffic.`;
  return "No proxy was attached.";
}

export default function BrowserbaseLoginCard({ onLinked, initialNickname = "", keepProxy = false, active = true, onBusy }: {
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  /** A row's re-login: bind nothing, so the account keeps the proxy it is on. Else the relay's automatic proxy. */
  keepProxy?: boolean;
  /** Shown (the start button in the footer); false while the other sign-in is. */
  active?: boolean;
  /** Hears whether a job is running (false again on unmount). */
  onBusy?: (running: boolean) => void;
}) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const linkedRef = useRef<string | null>(null);
  const liveRef = useRef<HTMLDivElement | null>(null);
  const mountedRef = useRef(false);
  /** The job to stop on unmount: set once started, cleared once it ends. */
  const runningJobRef = useRef<string | null>(null);
  /** When status reads started failing in a row (not 404); null after a good read. */
  const failingSinceRef = useRef<number | null>(null);

  const startM = useMutation<RemoteLoginStatus, RelayError, void>({
    mutationFn: async () => {
      const job = await relay.post<RemoteLoginStatus>("/admin/login/remote/start", {
        email: email.trim(), password, backend: "browserbase",
        // No choice: the relay's default (its proxy pool when it has one, else none; an account's binding stays).
        proxy: keepProxy ? "none" : undefined,
        nickname: initialNickname.trim() || undefined,
      });
      // The card went away while the start was in flight: nobody can stop this job, so stop it now.
      if (!mountedRef.current) relay.post(`${jobPath(job.id)}/cancel`).catch(() => {});
      else runningJobRef.current = job.id;
      return job;
    },
    onSuccess: (job) => {
      setErr(null);
      setPassword("");
      failingSinceRef.current = null;
      setJobId(job.id);
    },
    onError: (e) => setErr(`Couldn't start the login: ${e.message}`),
  });

  const statusQ = useQuery<RemoteLoginStatus>({
    queryKey: ["remote-login", jobId],
    queryFn: async () => {
      try {
        const s = await relay.get<RemoteLoginStatus>(jobPath(jobId!));
        failingSinceRef.current = null;
        return s;
      } catch (e) {
        if (isLost(e)) throw e;
        const since = (failingSinceRef.current ??= Date.now());
        throw Date.now() - since >= POLL_GIVE_UP_MS ? new PollGaveUp((e as Error).message) : e;
      }
    },
    enabled: !!jobId,
    // A 404 is final (a relay restart, or the job expired): no retry, the poll stops and the form comes back. Reads
    // failing for POLL_GIVE_UP_MS straight stop the poll too (Try again resumes it).
    retry: (n, e) => !isLost(e) && !gaveUp(e) && n < 3,
    // eslint-disable-next-line local/no-fixed-polling -- remote-login job has no SSE event; stops when the job ends
    refetchInterval: (q) => (isLost(q.state.error) || gaveUp(q.state.error) || (q.state.data && TERMINAL.has(q.state.data.state)) ? false : 1500),
  });
  const status = statusQ.data;
  const lost = isLost(statusQ.error);
  const stalled = gaveUp(statusQ.error);
  /** A status read failing (not 404): shown while the job is still counted as running. */
  const readErr = statusQ.isError && !lost ? statusQ.error.message : null;
  const running = !!jobId && !lost && !(status && TERMINAL.has(status.state));

  useEffect(() => {
    runningJobRef.current = running ? jobId : null;
  }, [running, jobId]);
  useReportBusy(running, onBusy);
  // Unmount only (no deps): stop a job still running.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const id = runningJobRef.current;
      if (id) relay.post(`${jobPath(id)}/cancel`).catch(() => {});
    };
  }, []);

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

  /** Polls again after the poll gave up. */
  const resume = () => { failingSinceRef.current = null; void statusQ.refetch(); };
  const cancel = () => {
    if (!jobId) return;
    const stop = relay.post(`${jobPath(jobId)}/cancel`).catch(() => {});
    if (stalled) void stop.then(resume); // the poll is off: read the stop back
  };

  const canStart = email.trim() !== "" && password !== "" && !startM.isPending && !running;

  const startLabel = startM.isPending ? "Starting browser…" : lost || (status && TERMINAL.has(status.state)) ? "Try again" : "Start browser login";

  return (
    <div className="space-y-4">
      <IfHelp className="mt-0 text-[14px] leading-[22px]">
        {keepProxy ? "Keeps its current proxy." : "Proxy assigned automatically (an account already on one keeps it). You can add yours after linking."}
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
          {lost ? <div role="alert" className="text-err text-sm whitespace-pre-wrap">Login failed: {LOST}</div> : <>
            {status?.state === "error" && <div role="alert" className="text-err text-sm whitespace-pre-wrap">Login failed: {status.error}</div>}
            {status?.state === "cancelled" && <div className="text-muted text-sm">Login cancelled.</div>}
          </>}

          {active && (
            <EditorFooter>
              <IfButton type="submit" form={BB_FORM_ID} variant="primary" disabled={!canStart}>{startLabel}</IfButton>
            </EditorFooter>
          )}
        </form>
      )}

      {running && (
        <div className="space-y-3 text-sm">
          <div className="flex items-start justify-between gap-3">
            <p role="status" className="text-fg">
              {status ? STATE_TEXT[status.state] ?? status.message : "Waiting for the login's first status…"}
            </p>
            <IfButton onClick={cancel}>Stop login</IfButton>
          </div>
          {readErr && (
            <div role="alert" className="space-y-2 text-err text-sm">
              <p className="whitespace-pre-wrap">
                {stalled
                  ? `Couldn't read this login's status for ${POLL_GIVE_UP_MS / 1000} seconds (${readErr}), so the card stopped checking. The login may still be running: try again, or stop it.`
                  : `Couldn't read this login's status (${readErr}). Still trying…`}
              </p>
              {stalled && <IfButton onClick={resume}>Try again</IfButton>}
            </div>
          )}
          {status?.state === "otp" && <OtpCodeForm jobId={status.id} message={status.message} inputId="bb-otp" />}
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

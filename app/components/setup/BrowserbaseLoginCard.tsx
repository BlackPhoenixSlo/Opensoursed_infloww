"use client";


import { accountSessionCaptured } from "@/lib/accountSession";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { relay, RelayError } from "@/lib/relay";
import { EditorFooter } from "@/components/ui/ifModal";
import { IfButton, IfHelp, IfInput, IfLabel } from "@/components/ui/infloww";
import {
  jobPath, stateText, TERMINAL, type RemoteLoginStatus,
} from "@/components/setup/remoteLogin";
import { OtpCodeForm } from "@/components/setup/RemoteLoginOtp";
import { useReportBusy } from "@/components/setup/useReportBusy";
import { BRAND_NAME } from "@/lib/brand";
import { DEFAULT_PLATFORM, PLATFORM_NAME, platformRow, type AccountPlatform, type Platform, type PlatformRow } from "@/lib/platform";

export type { RemoteLoginStatus };

const BB_FORM_ID = "browser-login-form";
const LOGIN_ID: Record<Platform, { label: string; type: "email" | "text" }> = {
  onlyfans: { label: "email", type: "email" },
  fansly: { label: "username or email", type: "text" },
};

const LOST = "the relay lost this login (it restarted, or the login expired). Try again.";
const isLost = (e: unknown) => e instanceof RelayError && e.status === 404;
export const POLL_GIVE_UP_MS = 30_000;
class PollGaveUp extends Error {}
const gaveUp = (e: unknown) => e instanceof PollGaveUp;

function attachedText(s: RemoteLoginStatus) {
  if (s.proxy === "infloww") return `The ${BRAND_NAME} proxy is attached for all later traffic.`;
  if (s.proxy === "custom") return `Proxy ${s.proxy_label} is attached for all later traffic.`;
  return "No proxy was attached.";
}

interface CardProps {
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  keepProxy?: boolean;
  active?: boolean;
  onBusy?: (running: boolean) => void;
  expectedAccountId?: string;
}

export default function BrowserbaseLoginCard({ platform = DEFAULT_PLATFORM, ...props }: CardProps & { platform?: AccountPlatform }) {
  const row = platformRow(platform);
  if (!row) return <IfHelp className="mt-0 text-[14px] leading-[22px]">{PLATFORM_NAME[platform]}</IfHelp>;
  return <LoginCard {...props} row={row} />;
}

function LoginCard({
  onLinked, initialNickname = "", keepProxy = false, active = true, onBusy, row, expectedAccountId,
}: CardProps & { row: PlatformRow }) {
  const platform = row.key;
  const site = row.label;
  const loginId = LOGIN_ID[platform];
  const isDefault = platform === DEFAULT_PLATFORM;
  const ids = isDefault ? "bb" : `bb-${platform}`;
  const formId = isDefault ? BB_FORM_ID : `${BB_FORM_ID}-${platform}`;
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const linkedRef = useRef<string | null>(null);
  const liveRef = useRef<HTMLDivElement | null>(null);
  const mountedRef = useRef(false);
  const runningJobRef = useRef<string | null>(null);
  const failingSinceRef = useRef<number | null>(null);

  const startM = useMutation<RemoteLoginStatus, RelayError, void>({
    mutationFn: async () => {
      const job = await relay.post<RemoteLoginStatus>("/admin/login/remote/start", {
        email: email.trim(), password, backend: "browserbase",
        platform: isDefault ? undefined : platform,
        ...(expectedAccountId === undefined ? {} : { expected_account_id: expectedAccountId }),
        proxy: keepProxy ? "none" : undefined,
        nickname: initialNickname.trim() || undefined,
      });
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
    onError: (e) => {
      setErr(`Couldn't start the login: ${e.message}`);
      onBusy?.(false);
    },
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
    retry: (n, e) => !isLost(e) && !gaveUp(e) && n < 3,
    // eslint-disable-next-line local/no-fixed-polling -- remote-login job has no SSE event; stops when the job ends
    refetchInterval: (q) => (isLost(q.state.error) || gaveUp(q.state.error) || (q.state.data && TERMINAL.has(q.state.data.state)) ? false : 1500),
  });
  const status = statusQ.data;
  const lost = isLost(statusQ.error);
  const stalled = gaveUp(statusQ.error);
  const readErr = statusQ.isError && !lost ? statusQ.error.message : null;
  const running = !!jobId && !lost && !(status && TERMINAL.has(status.state));

  useEffect(() => {
    runningJobRef.current = running ? jobId : null;
  }, [running, jobId]);
  useReportBusy(startM.isPending || running, onBusy);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Nothing else could stop a job still running here; it would still link and bind an account.
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

  const resume = () => { failingSinceRef.current = null; void statusQ.refetch(); };
  const cancel = () => {
    if (!jobId) return;
    const stop = relay.post(`${jobPath(jobId)}/cancel`).catch(() => {});
    if (stalled) void stop.then(resume);
  };

  const canStart = email.trim() !== "" && password !== "" && !startM.isPending && !running;

  const startLabel = startM.isPending ? "Starting browser…" : lost || (status && TERMINAL.has(status.state)) ? "Try again" : "Start browser login";

  return (
    <div className="space-y-4">
      <IfHelp className="mt-0 text-[14px] leading-[22px]">
        {!row.bindsProxy ? `${site} traffic after login uses the server IP.` : keepProxy ? "Keeps its current proxy." : "Proxy assigned automatically (an account already on one keeps it). You can add yours after linking."}
      </IfHelp>

      {!running && !done && (
        <form
          id={formId} className="space-y-4"
          onSubmit={(e) => { e.preventDefault(); if (active && canStart) { onBusy?.(true); startM.mutate(); } }}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <IfLabel htmlFor={`${ids}-email`}>{`${site} ${loginId.label}`}</IfLabel>
              <IfInput
                id={`${ids}-email`} type={loginId.type} inputMode="email" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" placeholder="creator@example.com"
                className="w-full"
              />
            </div>
            <div>
              <IfLabel htmlFor={`${ids}-password`}>{site} password</IfLabel>
              <IfInput
                id={`${ids}-password`} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
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
              <IfButton type="submit" form={formId} variant="primary" disabled={!canStart}>{startLabel}</IfButton>
            </EditorFooter>
          )}
        </form>
      )}

      {running && (
        <div className="space-y-3 text-sm">
          <div className="flex items-start justify-between gap-3">
            <p role="status" className="text-fg">
              {status ? stateText(site)[status.state] ?? status.message : "Waiting for the login's first status…"}
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
          {status?.state === "otp" && <OtpCodeForm jobId={status.id} message={status.message} inputId={`${ids}-otp`} site={site} />}
          {liveUrl ? (
            <div ref={liveRef} className="space-y-2">
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
          <p className="text-ok">Account {status.account_id} added. {row.bindsProxy ? attachedText(status) : "Later traffic uses the server IP."}</p>
        </div>
      )}
    </div>
  );
}

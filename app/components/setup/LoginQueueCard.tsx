"use client";

/**
 * LoginQueueCard — paste many OnlyFans logins, one `email<separator>password` per line (ultra-mode ticket 11; relay:
 * service/login_queue.py via POST /admin/login/remote/queue). The relay logs them in one at a time with the Browser
 * login (Browserbase) on its default proxy, the Add creator card's: the Inflowwww proxy when the relay has one, an
 * account already on a proxy keeps it; adding one is never required. Bad lines come back by number, never their text.
 *
 * Each entry shows its state; one on OnlyFans' 2FA prompt gets the shared code field (RemoteLoginOtp), one on a check
 * a link to its live view. A login that fails or runs out of time is also filed as a notification, and the queue goes
 * on. The queue id and each entry's email + state are kept per browser (the id also in `?queue=`, the notification's
 * link), so a reload resumes it; a queue the relay no longer has (it restarted, or a newer paste replaced it) lists
 * what was seen, done and not. With none open, or when Start fails without a sure refusal (no answer, a 409, a 5xx),
 * the card opens the owner's running queue; the error shows only when there is none. Polling goes on until every
 * entry ended (after Stop queue the running login winds down). The paste is cleared once the relay has it.
 *
 * State: loginQueue.ts (this only dispatches).
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useReducer } from "react";

import { errText } from "@/lib/errText";
import { relay, RelayError } from "@/lib/relay";
import { IfButton, IfHelp, IfLabel, IfTextArea } from "@/components/ui/infloww";
import { OtpCodeForm } from "@/components/setup/RemoteLoginOtp";
import {
  badLinesOf, buildPayload, canSubmit, entriesOf, entryNote, INITIAL, isPolling, isRunning, loginQueueReducer,
  lookForQueue, MAX_PASTE, parseStored, pollEvery, storedOf, type BadLine, type QueueView,
} from "@/components/setup/loginQueue";

export const LOGIN_QUEUE_KEY = "chatterly:login_queue";
const QUEUE = "/admin/login/remote/queue";
const queuePath = (id: string) => `${QUEUE}/${encodeURIComponent(id)}`;
const isLost = (e: unknown) => e instanceof RelayError && e.status === 404;

export default function LoginQueueCard({ linkedQueueId = null }: { linkedQueueId?: string | null }) {
  const qc = useQueryClient();
  const [s, send] = useReducer(loginQueueReducer, INITIAL);
  const running = isRunning(s);

  useEffect(() => {
    let raw: string | null = null;
    try { raw = window.localStorage.getItem(LOGIN_QUEUE_KEY); } catch { /* safari private */ }
    send({ type: "hydrate", stored: parseStored(raw) });
  }, []);
  useEffect(() => {
    if (linkedQueueId) send({ type: "link", queueId: linkedQueueId });
  }, [linkedQueueId]);
  const stored = storedOf(s);
  useEffect(() => {
    if (!s.hydrated) return;
    try {
      if (stored) window.localStorage.setItem(LOGIN_QUEUE_KEY, stored);
      else window.localStorage.removeItem(LOGIN_QUEUE_KEY);
    } catch { /* quota */ }
    const url = new URL(window.location.href);
    if ((url.searchParams.get("queue") ?? null) === s.queueId) return;
    if (s.queueId) url.searchParams.set("queue", s.queueId);
    else url.searchParams.delete("queue");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  }, [s.hydrated, s.queueId, stored]);
  // None open once hydrated: the owner's running queue (e.g. Start's answer was lost) is opened.
  const hydratedEmpty = s.hydrated && !s.queueId;
  useEffect(() => {
    if (hydratedEmpty) void currentQueue().then((view) => view && send({ type: "adopt", view }));
  }, [hydratedEmpty]);

  const pollQ = useQuery<QueueView>({
    queryKey: ["login-queue", s.queueId],
    queryFn: () => relay.get<QueueView>(queuePath(s.queueId!)),
    enabled: isPolling(s),
    retry: (n, e) => !isLost(e) && n < 3,
    // eslint-disable-next-line local/no-fixed-polling -- the login queue has no SSE event; stops when it ends
    refetchInterval: (q) => pollEvery(q.state.data, isLost(q.state.error)),
  });
  useEffect(() => {
    if (pollQ.data) send({ type: "polled", view: pollQ.data });
  }, [pollQ.data]);
  useEffect(() => {
    if (s.queueId && isLost(pollQ.error)) send({ type: "lost", queueId: s.queueId });
  }, [pollQ.error, s.queueId]);
  const doneCount = s.view?.entries.filter((e) => e.state === "done").length ?? 0;
  useEffect(() => {
    if (doneCount > 0) for (const key of ["accounts", "proxies", "health-all"]) qc.invalidateQueries({ queryKey: [key] });
  }, [doneCount, qc]);

  /** The owner's last queue, if the relay has one. */
  async function currentQueue(): Promise<QueueView | null> {
    try {
      return await relay.get<QueueView>(QUEUE);
    } catch {
      return null; // 404: none
    }
  }
  async function start() {
    const body = buildPayload(s);
    if (!body) return;
    send({ type: "start" });
    try {
      const out = await relay.post<QueueView & { bad_lines: BadLine[] }>(QUEUE, body);
      send({ type: "started", view: out, badLines: out.bad_lines ?? [] });
    } catch (e) {
      const current = lookForQueue(e instanceof RelayError ? e.status : null) ? await currentQueue() : null;
      send({ type: "startFailed", message: errText(e), badLines: e instanceof RelayError ? badLinesOf(e.body) : [],
        current });
    }
  }
  async function cancel() {
    if (!s.queueId) return;
    try {
      send({ type: "polled", view: await relay.post<QueueView>(`${queuePath(s.queueId)}/cancel`) });
    } catch (e) {
      if (isLost(e)) send({ type: "lost", queueId: s.queueId });
    }
  }

  const view = s.view;
  return (
    <div className="space-y-4">
      <IfHelp className="mt-0 text-[14px] leading-[22px]">
        Proxy assigned automatically (an account already on one keeps it). You can add yours after linking.
      </IfHelp>

      {!running && (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void start(); }}>
          <div>
            <IfLabel htmlFor="login-paste">OnlyFans logins, one per line</IfLabel>
            <IfTextArea
              id="login-paste" rows={6} value={s.text} maxLength={MAX_PASTE} spellCheck={false} autoCapitalize="none"
              autoCorrect="off" autoComplete="off" placeholder={"creator1@example.com:password\ncreator2@example.com password"}
              onChange={(e) => send({ type: "edit", text: e.target.value })}
              className="w-full font-mono text-[13px]"
            />
            <IfHelp>
              Email, then <code>:</code>, <code>|</code>, a tab or a space, then the password. They log in one at a
              time; passwords are used once and never stored.
            </IfHelp>
          </div>
          {s.error && <div role="alert" className="text-err text-sm whitespace-pre-wrap break-words">{s.error}</div>}
          <div className="flex flex-wrap gap-2">
            <IfButton type="submit" variant="primary" disabled={!canSubmit(s)}>
              {s.starting ? "Starting…" : "Log them in"}
            </IfButton>
            {s.queueId && <IfButton type="button" onClick={() => send({ type: "reset" })}>Clear finished</IfButton>}
          </div>
        </form>
      )}

      {s.badLines.length > 0 && (
        <ul aria-label="Skipped lines" className="space-y-1 text-sm text-warn">
          {s.badLines.map((b) => <li key={b.line}>Line {b.line} skipped: {b.reason}</li>)}
        </ul>
      )}

      {s.queueId && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p role="status" className="text-sm text-fg">
              {s.interrupted ? "This queue is no longer on the relay. Paste the logins not done again."
                : !view ? "Reading the queue…"
                : view.state === "running" ? "Logging in, one at a time…"
                : view.state === "cancelled" ? "Queue stopped." : "Queue finished."}
            </p>
            {running && <IfButton onClick={() => void cancel()}>Stop queue</IfButton>}
          </div>
          {pollQ.isError && !isLost(pollQ.error) && (
            <p role="alert" className="text-sm text-err">Couldn&apos;t read the queue ({pollQ.error.message}). Still trying…</p>
          )}
          <ul className="divide-y divide-border rounded-lg border border-border">
            {entriesOf(s).map((e) => (
              <li key={e.email} data-state={e.state} className="space-y-2 px-3 py-2.5 text-sm">
                <p className="break-all font-medium text-fg">{e.email}</p>
                <p className={e.state === "error" ? "text-err" : e.state === "done" ? "text-ok" : "text-fg-dim"}>
                  {entryNote(e, s.interrupted)}
                </p>
                {!s.interrupted && e.state === "otp" && e.job_id && (
                  <OtpCodeForm jobId={e.job_id} message={e.message} inputId={`otp-${e.job_id}`} />
                )}
                {!s.interrupted && e.live_view_url && (
                  <a href={e.live_view_url} target="_blank" rel="noopener noreferrer"
                    className="flex h-8 w-full items-center justify-center rounded-md border border-border px-[15px] text-[14px] text-fg hover:border-accent hover:text-accent md:inline-flex md:w-auto">
                    Open live view full screen
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

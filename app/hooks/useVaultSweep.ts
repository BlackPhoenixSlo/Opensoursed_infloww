"use client";


import { useCallback, useEffect, useRef, useState } from "react";
import {
  useQuery,
  useQueryClient,
  type QueryKey,
  type UseQueryResult,
} from "@tanstack/react-query";

import { fmtAgo } from "@/lib/format";
import { announceApiKeyError, ApiKeyError, relay, RelayError, type ApiKeyErrorPayload } from "@/lib/relay";

export type SweepKind = "describe-all" | "flags-all" | "harvest-keywords";

export interface SweepProgress {
  total: number;
  done: number;
  capped?: boolean;
  failed?: number;
  error?: string;
  notice?: string;
  aborted?: boolean;
  needs_review?: number;
  matches?: number | null;
  key_error?: ApiKeyErrorPayload | null;
  stop?: { message: string; fix: string } | null;
  finished_at?: string;
}

export const FAILED_NOTE_MAX_MS = 24 * 3600 * 1000;

export interface SweepStatus {
  running: boolean;
  progress: SweepProgress | null;
}

const POLL_MS = 2500;
const REFRESH_EVERY = 10;

export function sweepStatusKey(kind: SweepKind, accountId: string | null): QueryKey {
  return ["vault-sweep", kind, accountId];
}

export function useSweepStatus<T extends SweepStatus = SweepStatus>(
  kind: SweepKind,
  accountId: string | null,
  opts: { enabled?: boolean; pollWhileIdle?: boolean } = {},
): UseQueryResult<T> {
  const { enabled = true, pollWhileIdle = false } = opts;
  return useQuery<T>({
    queryKey: sweepStatusKey(kind, accountId),
    enabled: !!accountId && enabled,
    queryFn: () =>
      relay.get<T>(
        `/admin/vault-ai/${kind}/status?account_id=${encodeURIComponent(accountId!)}`,
      ),
    // eslint-disable-next-line local/no-fixed-polling -- stops when the job ends (pollWhileIdle: TODO verify)
    refetchInterval: (q) => (pollWhileIdle || q.state.data?.running ? POLL_MS : false),
    // Overrides the app-wide 3-day staleTime (a cached `running: false` would never poll) and no refetch on window focus (a backgrounded tab would go stale).
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
}

export interface VaultSweepOptions {
  kind: SweepKind;
  accountId: string | null;
  liveKeys?: QueryKey[];
  settleKeys?: QueryKey[];
  onSettled?: (status: SweepStatus) => void;
}

export interface VaultSweep {
  status: SweepStatus | undefined;
  progress: SweepProgress | null;
  running: boolean;
  busy: boolean;
  start: (body?: Record<string, unknown>) => Promise<string | null>;
}

export function useVaultSweep(opts: VaultSweepOptions): VaultSweep {
  const { kind, accountId } = opts;
  const qc = useQueryClient();
  const query = useSweepStatus(kind, accountId);
  const [starting, setStarting] = useState(false);

  const status = query.data;
  const running = !!status?.running;

  // Latest callbacks/keys via ref so neither effect lists a fresh identity and loops the settle edge.
  const latest = useRef(opts);
  latest.current = opts;

  const refresh = useCallback(
    (keys: QueryKey[] | undefined) => {
      for (const key of keys ?? []) qc.invalidateQueries({ queryKey: key });
    },
    [qc],
  );

  const bucket = Math.floor((status?.progress?.done ?? 0) / REFRESH_EVERY);
  useEffect(() => {
    if (!accountId || !running) return;
    refresh(latest.current.liveKeys);
  }, [accountId, running, bucket, refresh]);

  const seen = useRef<{ acct: string | null; running: boolean }>({
    acct: null,
    running: false,
  });
  useEffect(() => {
    const prev = seen.current;
    seen.current = { acct: accountId, running };
    // Keyed by account: switching chip mid-sweep is a different sweep, not a finish.
    if (!accountId || prev.acct !== accountId) return;
    if (running || prev.running === running) return;
    refresh(latest.current.liveKeys);
    refresh(latest.current.settleKeys);
    if (status?.progress?.key_error) announceApiKeyError(status.progress.key_error);
    if (status) latest.current.onSettled?.(status);
  }, [accountId, running, status, refresh]);

  const start = useCallback(
    async (body?: Record<string, unknown>): Promise<string | null> => {
      if (!accountId) return null;
      setStarting(true);
      let refusal: string | null = null;
      try {
        await relay
          .post(`/admin/vault-ai/${kind}`, { account_id: accountId, ...body }, { accountId })
          .catch((e: unknown) => {
            // A 409 already_running is not a refusal: clearing the label then put "Describe all" back over a running sweep.
            if (!(e instanceof RelayError && e.status === 409)) refusal = refusalText(e);
          });
        await qc
          .refetchQueries({ queryKey: sweepStatusKey(kind, accountId) })
          .catch(() => {});
      } finally {
        setStarting(false);
      }
      return refusal;
    },
    [accountId, kind, qc],
  );

  return {
    status,
    progress: status?.progress ?? null,
    running,
    busy: running || starting,
    start,
  };
}


export const WHOLE_VAULT = "Ask the owner: this needs access to the whole vault.";
export const GENERIC_REFUSAL = "The relay could not do that. Try again in a minute.";

function objectDetail(err: unknown): Record<string, unknown> | null {
  if (!(err instanceof RelayError)) return null;
  const body = err.body as { detail?: unknown } | null | undefined;
  const detail = body && typeof body === "object" ? body.detail : undefined;
  return detail && typeof detail === "object" && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

export function errorCode(err: unknown): string | null {
  const code = objectDetail(err)?.error;
  return typeof code === "string" ? code : null;
}

export function refusalText(err: unknown): string {
  if (err instanceof ApiKeyError) return `${err.payload.message} ${err.payload.fix}`;
  if (err instanceof RelayError) {
    const body = err.body as { detail?: unknown } | null | undefined;
    const raw = body && typeof body === "object" ? body.detail : undefined;
    if (typeof raw === "string" && raw.trim()) return raw;
    const d = objectDetail(err);
    if (d) {
      if (typeof d.blocked_reason === "string" && d.blocked_reason.trim()) return d.blocked_reason;
      if (d.error === "folder_not_allowed") return WHOLE_VAULT;
      if (typeof d.message === "string" && d.message.trim()) return d.message;
    }
    return GENERIC_REFUSAL;
  }
  return "Could not reach the relay.";
}


// `fallback` is the DB-derived count: the live counter is an in-memory relay dict, absent just after start and after a restart, which read "0/0".
export function sweepCounts(
  progress: SweepProgress | null,
  fallback?: { done: number; total: number },
): { done: number; total: number } | null {
  if (progress && progress.total > 0) return { done: progress.done, total: progress.total };
  if (fallback && fallback.total > 0) return fallback;
  return null;
}

function noticeLine(progress: SweepProgress | null): string {
  return progress?.notice && progress.notice !== progress.error ? progress.notice : "";
}

export function describeSweepText(
  progress: SweepProgress | null,
  fallback?: { done: number; total: number },
): { label: string; title: string } {
  const counts = sweepCounts(progress, fallback);
  const label = counts
    ? `${counts.done}/${counts.total}${progress?.capped ? " (cap hit)" : ""}`
    : "starting…";
  const title = [
    `Describing ${label} — keeps running if you close this page.`,
    progress?.failed ? `${progress.failed} could not be described.` : "",
    progress?.error ? `First error: ${progress.error}` : "",
    noticeLine(progress),
  ]
    .filter(Boolean)
    .join("\n");
  return { label, title };
}

export function sweepAbortedNote(
  progress: SweepProgress | null,
  now: number = Date.now(),
): { text: string; detail: string; tone: "warn" | "info" } | null {
  const stop = progress?.key_error ?? progress?.stop;
  if (stop) {
    const detail = [stop.fix, noticeLine(progress)].filter(Boolean).join("\n");
    return { text: stop.message, detail, tone: "warn" };
  }
  if (!progress) return null;
  if (progress.aborted) {
    const left = Math.max(0, (progress.total || 0) - (progress.done || 0));
    return {
      text: `Stopped early — ${left} left. Press again to resume.`,
      detail: [progress.error || "The sweep ended before it finished.", noticeLine(progress)]
        .filter(Boolean).join("\n"),
      tone: "warn",
    };
  }
  const failed = progress.failed || 0;
  const at = progress.finished_at ? Date.parse(progress.finished_at) : NaN;
  if (!failed || !Number.isFinite(at) || now - at > FAILED_NOTE_MAX_MS) return null;
  return {
    text: `Last run ${fmtAgo(progress.finished_at) ?? ""}: ${failed} of ${progress.total} failed.`,
    detail: [
      progress.error ? `First error: ${progress.error}` : "No error was recorded.",
      noticeLine(progress),
    ].filter(Boolean).join("\n"),
    tone: failed >= (progress.done || 0) ? "warn" : "info",
  };
}

export function harvestSweepLabel(progress: SweepProgress | null): string {
  const counts = sweepCounts(progress);
  if (!counts) return "starting…";
  const m = progress?.matches;
  return m == null ? `${counts.done}/${counts.total}` : `${counts.done}/${counts.total} · ${m} hits`;
}

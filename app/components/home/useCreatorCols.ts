"use client";


import { useCallback, useEffect, useRef, useState } from "react";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";

import { APPLIED_SETTINGS_KEY, useAppliedSettings, useAppliedSettingsAfterMount } from "@/lib/appliedSettings";
import { RelayError, request } from "@/lib/relay";
import { usePrincipalId } from "@/hooks/useEmployeeKey";
import { creatorColsQueue, forgetCreatorColsQueue } from "@/lib/creatorColsQueue";

import { shownKeys } from "./creatorCols";

const SAVE_DELAY_MS = 600;

const put = (cols: string[]) =>
  request("/admin/settings/reports", { method: "PUT", body: JSON.stringify({ creator_cols: cols }), keepalive: true });

// One save queue for every mount: an older layout never lands after a newer one.
const queue = creatorColsQueue;
let current = "";

export { forgetCreatorColsQueue };

function send(qc: QueryClient) {
  const job = queue.next;
  if (!job || queue.inFlight) return;
  queue.next = null;
  if (current && job.principal !== current) return;
  queue.inFlight = true;
  put(job.cols)
    .then(() => { if (!queue.next) void qc.invalidateQueries({ queryKey: APPLIED_SETTINGS_KEY }); })
    .catch((e: unknown) => {
      // A chatter's 401 means its change is this visit's only; otherwise revert to the Relay's layout.
      if (!(e instanceof RelayError && e.status === 401) && !queue.next) job.revert();
    })
    .finally(() => {
      queue.inFlight = false;
      send(qc);
    });
}

export function useCreatorCols(): [string[], ((next: string[]) => void) | null, (() => void) | null] {
  const qc = useQueryClient();
  const cachedRead = useAppliedSettings();
  const cached = cachedRead.isPlaceholderData ? undefined : cachedRead.data?.reports?.creator_cols;
  // Read fresh on every mount: the cached Applied snapshot can predate the last save; changes wait for this read.
  const { settings: fresh, failed, retry, key: readKey } = useAppliedSettingsAfterMount(true);
  const [draft, setDraft] = useState<{ key: string; cols: string[] } | null>(null);
  const local = draft?.key === readKey ? draft.cols : null;
  const principal = usePrincipalId();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const save = useCallback(() => {
    clearTimeout(timer.current);
    send(qc);
  }, [qc]);

  const set = useCallback((next: string[]) => {
    setDraft({ key: readKey, cols: next });
    queue.next = { cols: next, principal, revert: () => setDraft(null) };
    clearTimeout(timer.current);
    timer.current = setTimeout(save, SAVE_DELAY_MS);
  }, [save, readKey, principal]);

  useEffect(() => { current = principal; }, [principal]);

  const pageHide = useCallback(() => {
    // The page is dying: a layout queued behind an in-flight save goes out now (keepalive) and is not replayed.
    const job = queue.next;
    if (queue.inFlight && job && (!current || job.principal === current)) {
      queue.next = null;
      clearTimeout(timer.current);
      put(job.cols).catch(() => {});
    } else save();
  }, [save]);

  useEffect(() => {
    window.addEventListener("pagehide", pageHide);
    return () => { window.removeEventListener("pagehide", pageHide); save(); };
  }, [pageHide, save]);

  const stored = fresh ? fresh.reports?.creator_cols : cached;
  return [local ?? shownKeys(stored), fresh ? set : null, failed ? retry : null];
}

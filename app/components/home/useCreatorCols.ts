"use client";

/** Creator statistics' column layout, the Agency's: read from the Applied settings, saved by the owner
 *  (`PUT /admin/settings/reports`) a moment after the last change, or at once on leaving the page. A chatter's
 *  session cannot save (401), so its change lasts this visit only.
 *
 *  The layout is read fresh on every mount: the persisted Applied snapshot counts as fresh for 60 s and can predate
 *  the last save, so a reload would paint the old order. Changes wait for that read (setter `null` until then), so
 *  a layout built on a stale read never overwrites the stored one; when it fails, the third value asks it again.
 *  A change shows only for the read it was made on (principal + Creator in scope), never another scope's. */

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

/** One save queue for every mount (leaving the page and opening it again mounts a new hook while the old one's save is
 *  in flight), so an older layout never lands after a newer one; a job never goes out under another principal's session
 *  (`current`: the mounted hook's). */
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
      // Not saved: back to the Relay's layout, unless a chatter (401; its change is this visit's only) or a newer
      // change is queued.
      if (!(e instanceof RelayError && e.status === 401) && !queue.next) job.revert();
    })
    .finally(() => {
      queue.inFlight = false;
      send(qc);
    });
}

export function useCreatorCols(): [string[], ((next: string[]) => void) | null, (() => void) | null] {
  const qc = useQueryClient();
  // Never another Creator's read shown while this one's loads (placeholder): the defaults until it lands.
  const cachedRead = useAppliedSettings();
  const cached = cachedRead.isPlaceholderData ? undefined : cachedRead.data?.reports?.creator_cols;
  // `readKey`: the Applied read's identity; a change belongs to the read it was made on.
  const { settings: fresh, failed, retry, key: readKey } = useAppliedSettingsAfterMount(true);
  const [draft, setDraft] = useState<{ key: string; cols: string[] } | null>(null);
  const local = draft?.key === readKey ? draft.cols : null;
  const principal = usePrincipalId();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // A moment after the last change, or at once on leaving the page (keepalive lets it land after the page is gone);
  // with a save in flight the layout waits in the queue.
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

  // The page is dying: a layout queued behind an in-flight save goes out now (keepalive) and is not replayed.
  const pageHide = useCallback(() => {
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

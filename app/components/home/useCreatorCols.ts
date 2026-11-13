"use client";

/** Creator statistics' column layout, the Agency's: read from the Applied settings, saved by the owner
 *  (`PUT /admin/settings/reports`) a moment after the last change, or at once on leaving the page. A chatter's
 *  session cannot save (401), so its change lasts this visit only.
 *
 *  The layout is read fresh on every mount: the persisted Applied snapshot counts as fresh for 60 s and can predate
 *  the last save, so a reload would paint the old order. Changes wait for that read (setter `null` until then), so
 *  a layout built on a stale read never overwrites the stored one. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { APPLIED_SETTINGS_KEY, useAppliedSettings, useAppliedSettingsAfterMount } from "@/lib/appliedSettings";
import { RelayError, request } from "@/lib/relay";

import { shownKeys } from "./creatorCols";

const SAVE_DELAY_MS = 600;

export function useCreatorCols(): [string[], ((next: string[]) => void) | null] {
  const qc = useQueryClient();
  const cached = useAppliedSettings().data?.reports?.creator_cols;
  const fresh = useAppliedSettingsAfterMount(true).settings;
  const [local, setLocal] = useState<string[] | null>(null);
  const pending = useRef<string[] | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const inFlight = useRef(false);

  // One save at a time, the latest pending layout next, so a slow earlier PUT never lands after a newer one.
  // Leaving the page sends at once (`force`): keepalive lets it land after the page is gone.
  const save = useCallback((force = false) => {
    clearTimeout(timer.current);
    if (inFlight.current && !force) return;
    const cols = pending.current;
    pending.current = null;
    if (!cols) return;
    inFlight.current = true;
    request("/admin/settings/reports", { method: "PUT", body: JSON.stringify({ creator_cols: cols }), keepalive: true })
      .then(() => { if (!pending.current) void qc.invalidateQueries({ queryKey: APPLIED_SETTINGS_KEY }); })
      .catch((e: unknown) => {
        // Not saved: back to the Relay's layout, unless a chatter (401; its change is this visit's only) or a newer
        // change is queued.
        if (!(e instanceof RelayError && e.status === 401) && !pending.current) setLocal(null);
      })
      .finally(() => {
        inFlight.current = false;
        if (pending.current) save();
      });
  }, [qc]);
  const flush = useCallback(() => save(true), [save]);

  const set = useCallback((next: string[]) => {
    setLocal(next);
    pending.current = next;
    clearTimeout(timer.current);
    timer.current = setTimeout(save, SAVE_DELAY_MS);
  }, [save]);

  useEffect(() => {
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, [flush]);

  const stored = fresh ? fresh.reports?.creator_cols : cached;
  return [local ?? shownKeys(stored), fresh ? set : null];
}

"use client";

/**
 * The Relay's OFM_NEW_WRITES_ENABLED switch (service/runtime_switches.py, default off) for the OF Manager controls new to
 * the mirror, per Creator: on for a Creator = the server's env on, not forced off box-wide (Settings › System) and not
 * forced off for that Creator (Settings › OF Manager writes). Two kinds:
 * - Relay-gated (a write OnlyFans did not get from the mirror before): Close all sessions, Block by country / IP, Social
 *   media's and Things I Like's add and remove, Streaming's Reset stream key and Blocked users' block and unblock, Edit
 *   profile's cover and avatar, Messaging's Tip-from-free-followers and Security's Fully private switches, a tracking
 *   link's Share. Off, their routes answer 404 (server._ofm_new_writes_on) or refuse their new keys (422).
 * - UI-only (the same request main already sends, so the Relay cannot tell them apart): Edit profile's Bio formatting
 *   (PATCH /users/me `about`; on, the Relay sanitizes it), email's Update frequency (the digest toggle's notifications
 *   PATCH), Home's and New post's Record video and Record voice (upload, post), vault/list's
 *   header More (vault list rename/delete), a chat's own-bubble extras Countdown, Copy as draft and Unsend PPV (ticket
 *   33; Unsend PPV is the menu's DELETE /messages/{id}). Off, only this switch hides them.
 * Off, the probe GET /api/of/ofm-writes (asked for the Creator in scope) answers 404: each binder and drawer leaves its control disabled with its Not-yet
 * title (the Bio saves as plain text; New post's Record keeps main's "not supported here" popup; the own-bubble extras
 * are not drawn at all, as main). Reads, hand-off links
 * and openers stay ungated. One cached probe read (useRelaySwitch, shared with ofMirrorGoLiveWindow's).
 */

import { useQuery } from "@tanstack/react-query";
import { relay } from "@/lib/relay";

export const OFM_WRITES_PATH = "/api/of/ofm-writes";
/** The probe's React Query key (with the Creator: `[OFM_WRITES_KEY, accountId]`). */
export const OFM_WRITES_KEY = "ofm-writes";

/** A Relay switch probe: true only when `get` answers `field` true; its 404 (switch off) or any failure is false. */
export async function switchOn(get: () => Promise<Record<string, unknown> | null | undefined>, field: string): Promise<boolean> {
  try {
    return (await get())?.[field] === true;
  } catch {
    return false;
  }
}

/** A Relay switch probe's query: GET `path` cached under `key`, and per Creator when `accountId` is given (sent as
 *  X-Account-Id, so the Relay answers for that Creator; each Creator is its own cache entry). A per-Creator probe is
 *  asked again each minute, so an open tab drops the controls within a minute of the owner's force-off. */
export function relaySwitchQuery(key: string, path: string, field: string, accountId?: string | null) {
  return {
    queryKey: accountId === undefined ? [key] : [key, accountId],
    queryFn: () => switchOn(() => relay.get<Record<string, unknown>>(path, accountId ? { accountId } : undefined), field),
    refetchInterval: accountId === undefined ? (false as const) : 60 * 1000,
  };
}

/** A Relay switch's probe GET `path` (`{[field]: true}`, 404 off), cached under `key`: false until it answers.
 *  `enabled`: this page has one of its controls. `accountId`: a per-Creator switch's Creator; null (none in scope)
 *  asks nothing and reads off. */
export function useRelaySwitch(key: string, path: string, field: string, enabled: boolean, accountId?: string | null): boolean {
  return (
    useQuery({
      ...relaySwitchQuery(key, path, field, accountId),
      enabled: enabled && accountId !== null,
      staleTime: 60 * 1000,
      retry: false,
    }).data === true
  );
}

/** Whether the new writes are on for `accountId` (false until the probe answers, or with no Creator in scope);
 *  `enabled`: this page has one of their controls. */
export const useOfmNewWrites = (enabled: boolean, accountId: string | null): boolean =>
  useRelaySwitch(OFM_WRITES_KEY, OFM_WRITES_PATH, "on", enabled, accountId);

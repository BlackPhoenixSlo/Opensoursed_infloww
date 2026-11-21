"use client";

/**
 * The Relay's OFM_NEW_WRITES_ENABLED switch (service/runtime_switches.py, default off) for the OF Manager controls new to
 * the mirror. Two kinds:
 * - Relay-gated (a write OnlyFans did not get from the mirror before): Close all sessions, Block by country / IP, Social
 *   media's and Things I Like's add and remove, Streaming's Reset stream key and Blocked users' block and unblock, Edit
 *   profile's cover and avatar, Messaging's Tip-from-free-followers and Security's Fully private switches, a tracking
 *   link's Share. Off, their routes answer 404 (server._ofm_new_writes_on) or refuse their new keys (422).
 * - UI-only (the same request main already sends, so the Relay cannot tell them apart): Edit profile's Bio formatting
 *   (PATCH /users/me `about`; on, the Relay sanitizes it), email's Update frequency (the digest toggle's notifications
 *   PATCH), Home's and New post's Record video and Record voice (upload, post), vault/list's
 *   header More (vault list rename/delete). Off, only this switch hides them.
 * Off, the probe GET /api/of/ofm-writes answers 404: each binder and drawer leaves its control disabled with its Not-yet
 * title (the Bio saves as plain text; New post's Record keeps main's "not supported here" popup). Reads, hand-off links
 * and openers stay ungated. One cached probe read (useRelaySwitch, shared with ofMirrorGoLiveWindow's).
 */

import { useQuery } from "@tanstack/react-query";
import { relay } from "@/lib/relay";

export const OFM_WRITES_PATH = "/api/of/ofm-writes";

/** A Relay switch probe: true only when `get` answers `field` true; its 404 (switch off) or any failure is false. */
export async function switchOn(get: () => Promise<Record<string, unknown> | null | undefined>, field: string): Promise<boolean> {
  try {
    return (await get())?.[field] === true;
  } catch {
    return false;
  }
}

/** A Relay switch's probe GET `path` (`{[field]: true}`, 404 off), cached under `key`: false until it answers.
 *  `enabled`: this page has one of its controls. */
export function useRelaySwitch(key: string, path: string, field: string, enabled: boolean): boolean {
  return (
    useQuery({
      queryKey: [key],
      queryFn: () => switchOn(() => relay.get<Record<string, unknown>>(path), field),
      enabled,
      staleTime: 60 * 1000,
      retry: false,
    }).data === true
  );
}

/** Whether the new writes are on (false until the probe answers); `enabled`: this page has one of their controls. */
export const useOfmNewWrites = (enabled: boolean): boolean => useRelaySwitch("ofm-writes", OFM_WRITES_PATH, "on", enabled);

"use client";

/**
 * The top bar's Clock button, Infloww's `ClockInOrOut` (bundle @10503600,
 * shown by `HeaderSignButton` @11153536), between the bell and the avatar (header @11162567).
 *
 * It reads `GET /admin/shifts/clock-status` (any session) and renders only
 * while the caller may clock in (`can_clock`) or has an open event. Idle it
 * reads "Clock in"; clocked in, "Clock out" and the elapsed time in Infloww's
 * `convertSeconds` format at 62% opacity, moved every 30 seconds. A click
 * asks "Confirm clock in?" / "Confirm clock out?", then clocks through
 * `useClock` (the agency-wide clock: no Creator), whose toast says "Clock in
 * successful" or a 409's "You are already clocked in". A chatter in two
 * Agencies (`reason: "pick_creator"`) opens `ClockDialog` to name a Creator.
 *
 * While clocked in, `useClockHeartbeat` renews the event after real input
 * (Infloww's `useMouseMoveDetection` @10588799 and `ClockTimeInterval`
 * @10626350), and a status that comes back with the event closed by Auto
 * clock out shows "You have been clocked out due to inactivity" once, or
 * Infloww's "…as your internet connection was lost." when the tab's
 * network attempts (heartbeats and status reads) had failed at the network
 * level with no success since, the first at or before the close. The Relay's sweep still
 * does the closing either way; only the line differs.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import ClockDialog from "@/components/shifts/ClockDialog";
import { ClockCheckLine, ClockOutLine } from "@/components/shell/inflowwIcons";
import { HEADER_TILE, HEADER_TILE_ICON } from "@/components/shell/headerTile";
import { useChatter } from "@/contexts/ChatterContext";
import { useUser } from "@/contexts/UserContext";
import { pushNotice } from "@/lib/notices";
import { RelayError } from "@/lib/relay";
import {
  CLOCK_STATUS_KEY, CLOCK_TEXT, clockHeartbeat, convertSeconds, useClock, type ClockEvent,
  type ClockStatus,
} from "@/lib/shifts";

const BUTTON =
  "text-xs px-3 py-1.5 rounded-lg bg-bg-elev-1 hover:bg-bg-elev-2 border border-border disabled:opacity-50";
const PRIMARY = "text-xs px-3 py-1.5 rounded-lg bg-accent text-white hover:opacity-90 disabled:opacity-50";

/** The input that counts as activity, Infloww's mouse and keyboard. */
const ACTIVITY = ["pointermove", "pointerdown", "keydown", "wheel"] as const;
/** The elapsed label's step. */
const TICK_MS = 30_000;

/** A fetch that never got an HTTP answer (a `RelayError` is an answer), or the browser offline. */
const networkFailed = (e: unknown) =>
  !(e instanceof RelayError) || (typeof navigator !== "undefined" && navigator.onLine === false);

/**
 * Renews the `open` event (`POST /clock-heartbeat`) every 60 seconds, or 30
 * with `minutes` (`auto_clock_out_minutes`) ≤ 3 as Infloww's
 * `ClockTimeInterval`, but only when there was input since the last beat, so
 * an idle open tab does not keep anyone clocked in. Each answer replaces the
 * cached ClockStatus; a beat that got no HTTP answer calls `onLost` with the
 * event's id. Nothing while `open` is null.
 */
export function useClockHeartbeat(open: ClockEvent | null, minutes: number, onLost: (eventId: number) => void) {
  const queryClient = useQueryClient();
  const openId = open?.clock_event_id ?? null;
  const lost = useRef(onLost);
  useEffect(() => { lost.current = onLost; });
  useEffect(() => {
    if (openId === null) return;
    let active = -1;
    let beat = Date.now();
    const mark = () => { active = Date.now(); };
    for (const type of ACTIVITY) window.addEventListener(type, mark, { passive: true });
    const id = window.setInterval(() => {
      if (active < beat) return;
      beat = Date.now();
      clockHeartbeat().then(
        (status) => queryClient.setQueryData<ClockStatus>(CLOCK_STATUS_KEY, status),
        // A failed beat: the next poll or beat reads the status again.
        (e) => { if (networkFailed(e)) lost.current(openId); },
      );
    }, minutes <= 3 ? 30_000 : 60_000);
    return () => {
      window.clearInterval(id);
      for (const type of ACTIVITY) window.removeEventListener(type, mark);
    };
  }, [minutes, openId, queryClient]);
}

/** The server's clock minus this device's, in ms, as of the latest status read (0 before one). */
const serverSkew = (query: UseQueryResult<ClockStatus>) =>
  query.data ? Date.parse(query.data.server_now) - query.dataUpdatedAt : 0;

/** "1 h 23 min" since `iso` by the server's clock (`skew`: server minus this
 *  device, in ms), re-read every 30 seconds. */
function Elapsed({ since, skew }: { since: string; skew: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="opacity-[.62] tabular-nums">
      {convertSeconds((now + skew - new Date(since).getTime()) / 1000)}
    </span>
  );
}

/**
 * The Auto clock out's notice, once per event, and the one record it reads:
 * the open event whose network attempts (a status read here, or a heartbeat
 * through the returned `onLost`) failed with no success since, and when the
 * first of them failed, by the server's clock. Every successful status read, a
 * heartbeat's answer included, first announces an Auto clock out it
 * reveals, then clears that record. The connection-lost line needs that
 * first failure at or before the close: a beat that fails after it (a laptop
 * waking with its network still down) found the event already closed for
 * inactivity.
 *
 * ASSUMPTION: "You have been clocked out due to inactivity" shows only for
 * an event this tab saw open, so a page opened after an Auto clock out does
 * not announce it. Rung 5: Infloww's client says it when it notices the idle
 * itself. Overturned if the owner wants it on the next visit too.
 */
function useAutoClockOutNotice(query: UseQueryResult<ClockStatus>) {
  const seenOpen = useRef(new Set<number>());
  const announced = useRef(new Set<number>());
  const lost = useRef<{ id: number; at: number } | null>(null);
  const status = query.data;
  const openId = status?.open?.clock_event_id ?? null;
  const skew = serverSkew(query);
  // The first failure counts: in an outage that outlasts the deadline the later ones come after the close.
  const markLost = useCallback((id: number) => {
    if (lost.current?.id !== id) lost.current = { id, at: Date.now() + skew };
  }, [skew]);

  useEffect(() => {
    if (query.error && openId !== null && networkFailed(query.error)) markLost(openId);
  }, [query.error, query.errorUpdateCount, openId, markLost]);
  useEffect(() => {
    if (!status) return;
    if (status.open) seenOpen.current.add(status.open.clock_event_id);
    const last = status.last_closed;
    if (!status.open && last?.close_reason === "auto" && seenOpen.current.has(last.clock_event_id)
        && !announced.current.has(last.clock_event_id)) {
      announced.current.add(last.clock_event_id);
      const failed = lost.current;
      const cut = failed?.id === last.clock_event_id && failed.at <= Date.parse(last.out_utc);
      const text = cut ? CLOCK_TEXT.connectionLost : CLOCK_TEXT.inactivity;
      pushNotice({ id: `clock:auto:${last.clock_event_id}`, text, label: "Time tracking" });
    }
    lost.current = null;
    // Every successful read: each carries a new `server_now`, so a new `status`.
  }, [status, query.dataUpdatedAt]);

  return markLost;
}

/** A window's clock session: the signed-in caller's `useClock`, the Auto
 *  clock out's notice, and the heartbeat after input. Every window that can
 *  hold an open event runs one. */
function useClockSession() {
  const { user } = useUser();
  const { chatter } = useChatter();
  const clock = useClock(!!user || !!chatter);
  const status = clock.status.data;
  const onLost = useAutoClockOutNotice(clock.status);
  useClockHeartbeat(status?.open ?? null, status?.auto_clock_out_minutes ?? 0, onLost);
  return clock;
}

/** The clock session with no button, for a window with no top bar (Messages
 *  Pro): input there keeps the caller's open event alive, and an Auto clock
 *  out says so, as in the main window. */
export function ClockHeartbeat() {
  useClockSession();
  return null;
}

export default function ClockButton() {
  const clock = useClockSession();
  const status = clock.status.data;
  const [confirming, setConfirming] = useState(false);

  if (!status || !clock.visible) return null;
  const open = status.open;
  const skew = serverSkew(clock.status);

  return (
    <>
      <button
        type="button"
        // Infloww's `HeaderSignButton`: the header tile with `ClockCheckLine`
        // ("Clock in") or `ClockOutLine` ("Clock out" and the time since).
        className={HEADER_TILE}
        disabled={clock.busy}
        // A chatter in two Agencies picks a Creator in ClockDialog instead of confirming.
        onClick={() => (clock.picks ? void clock.act() : setConfirming(true))}
      >
        {open ? <ClockOutLine aria-hidden className={HEADER_TILE_ICON} /> : <ClockCheckLine aria-hidden className={HEADER_TILE_ICON} />}
        {open ? (
          <>
            <span>{clock.label}</span>
            <span className="hidden sm:inline"><Elapsed since={open.in_utc} skew={skew} /></span>
          </>
        ) : clock.label}
      </button>
      {clock.picking && <ClockDialog onClose={clock.closePicker} />}
      <Dialog.Root open={confirming} onOpenChange={setConfirming}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[22rem] max-w-[calc(100vw-32px)] p-5 rounded-lg border border-border bg-bg space-y-4 outline-none"
          >
            {/* Infloww's sign modal has no title: the question is its body, and OK reads "Yes" (bundle @10634621). */}
            <Dialog.Title className="text-sm font-normal">
              {open ? CLOCK_TEXT.confirmOut : CLOCK_TEXT.confirmIn}
            </Dialog.Title>
            <div className="flex justify-end gap-2">
              <Dialog.Close asChild>
                <button type="button" className={BUTTON}>Cancel</button>
              </Dialog.Close>
              <button type="button" className={PRIMARY} onClick={() => { setConfirming(false); void clock.act(); }}>
                Yes
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

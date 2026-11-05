"use client";

/**
 * "Clock in and out" (docs/spec/phase-02-shifts-time-tracking.md, App;
 * user stories 19-26): a chatter picks one of the Creators it can access and
 * clocks in; the dialog then shows the open Clock event and Clock out.
 *
 * Since w4-a everyone else clocks in one click on the agency-wide clock
 * (`useClock`); this dialog opens only for a chatter linked to two Agencies
 * (ClockStatus `reason: "pick_creator"`), from the top bar's Clock button,
 * the "My shifts" card or the clock-in reminder, so the Creator names the
 * Agency. Its writes are `useClock`'s, so they toast as everywhere else.
 *
 * Everything comes from `GET /admin/shifts/me`: the Creators, each with its
 * own Agency's time-tracking flag, and the chatter's open Clock events. The
 * Relay decides the Agency (the one that owns the Creator) and the Shift an
 * event attaches to, so the dialog sends only the Creator or the event id.
 *
 * ASSUMPTION: while any Clock event is open the dialog shows only the open
 * events and their Clock out, not the Creator picker. Rung 5: the ticket's
 * "the dialog then shows the open Clock event and a Clock out button". A
 * chatter linked to two Agencies clocks in on the second one after clocking
 * out of the first. Overturned if such a chatter must hold an open event in
 * each Agency from this dialog at once (the Relay already allows it).
 */

import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";

import { IfButton, IfLabel, IfNativeSelect } from "@/components/ui/infloww";
import { IF_MODAL_BOX, IF_MODAL_MASK } from "@/components/ui/ifModal";
import { occurrenceLabel, useClock, useMyShifts } from "@/lib/shifts";

export const TIME_TRACKING_OFF = "Time tracking is off for your agency";


export default function ClockDialog({ onClose }: { onClose: () => void }) {
  const me = useMyShifts();
  const clock = useClock();
  const [picked, setPicked] = useState<string | null>(null);
  const busy = clock.busy;

  const accounts = me.data?.accounts ?? [];
  const open = me.data?.open_clocks ?? [];
  const accountId = picked ?? accounts[0]?.account_id ?? "";
  const account = accounts.find((a) => a.account_id === accountId);
  const creatorName = (id: string | null) => accounts.find((a) => a.account_id === id)?.display_name ?? id ?? "a Creator";

  let body;
  /** The pick-a-Creator case's primary, in the footer after Close (R7). */
  let action = null;
  if (me.isPending) {
    body = <p className="text-sm text-fg-dim">Loading…</p>;
  } else if (me.isError) {
    body = (
      <p className="text-sm text-err flex items-center gap-2">
        {`Couldn't load your shifts: ${me.error.message}`}
        <IfButton onClick={() => void me.refetch()}>Retry</IfButton>
      </p>
    );
  } else if (open.length > 0) {
    body = (
      <ul className="space-y-2">
        {open.map((ev) => (
          <li key={ev.clock_event_id} className="flex items-center gap-3 text-sm">
            <span className="flex-1">
              {`Clocked in on ${creatorName(ev.account_id)} since ${occurrenceLabel(ev.in_utc)}`}
            </span>
            <IfButton disabled={busy} onClick={() => void clock.clockOutNow(ev.clock_event_id)}>
              Clock out
            </IfButton>
          </li>
        ))}
      </ul>
    );
  } else if (accounts.length === 0) {
    body = <p className="text-sm text-fg-dim">You have no Creators to clock in on.</p>;
  } else {
    body = (
      <div className="space-y-3">
        <div>
          <IfLabel htmlFor="clock-creator">Creator</IfLabel>
          <IfNativeSelect id="clock-creator" aria-label="Creator" className="w-full" value={accountId}
            onChange={(e) => setPicked(e.target.value)}>
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>{a.display_name}</option>
            ))}
          </IfNativeSelect>
        </div>
        {account && !account.time_tracking_enabled && (
          <p className="text-sm text-fg-dim">{TIME_TRACKING_OFF}</p>
        )}
      </div>
    );
    action = (
      <IfButton variant="primary" disabled={busy || !account?.time_tracking_enabled}
        onClick={() => void clock.clockInNow(accountId)}>
        Clock in
      </IfButton>
    );
  }

  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        {/* IfModal's look on Radix: the 70% mask, the kit box, title 22px 24px, body 24px, footer right. */}
        <Dialog.Overlay className={`fixed inset-0 z-40 ${IF_MODAL_MASK}`} />
        <Dialog.Content
          aria-describedby={undefined}
          className={`fixed left-1/2 top-1/2 z-50 w-[416px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 ${IF_MODAL_BOX}`}
        >
          <Dialog.Title className="px-6 pt-[22px] text-[16px] font-semibold">Clock in and out</Dialog.Title>
          <div className="p-6 text-[14px]">{body}</div>
          <div className="flex justify-end gap-2 px-6 pb-5">
            <Dialog.Close asChild>
              <IfButton>Close</IfButton>
            </Dialog.Close>
            {action}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

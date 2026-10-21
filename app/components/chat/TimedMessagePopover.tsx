"use client";

/**
 * TimedMessagePopover — the ⏱ in the Composer's button row (docs/spec/
 * phase-04-composer-ppv-vault.md, Timed message, Timed reminder and
 * Contracts; Gap row 16). Two tabs:
 *
 * - "Timed message" holds the draft for a whole number of minutes, 1 to 60,
 *   by calling `onStart(minutes)`, which the Composer wires to its existing
 *   delayed submit. It holds no send state and adds no cancel: a queued Timed
 *   message is cancelled like any scheduled send.
 * - "Timed reminder" starts a 1–60 minute countdown for this Fan that sends
 *   nothing. This module owns it outright: one reminder per Fan in a
 *   module-level store (survives chat switches), its fire time under
 *   `chatterly:timed-reminder:<accountId>:<fanId>` (survives reloads), and
 *   `TimedReminderNotice`, the countdown / alert strip the Composer shows in
 *   its notice area.
 *
 * Under the "Timed message" tab, "Send at" +5m … +60m turn the Composer's
 * schedule mode on with "at" that far ahead (`onPreset`); they never send.
 * They moved here from the Composer's "+" overflow (TODO.md A2).
 */

import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { AlarmClock } from "lucide-react";

import { cn } from "@/lib/utils";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { playAlertOnce } from "@/lib/alertSounds";
import { readNotifSettings } from "@/lib/notifSettings";
import { osNotify } from "@/lib/osNotify";
import { EXECUTOR_MAX_MINUTES } from "@/hooks/useSendMessage";
import { POP, POP_HEAD, POP_PRIMARY, POP_ROW, ROW_ICON, usePopover } from "./ComposerToolbar";
import { FIELD } from "./PpvRow";

/* ── Timed reminder store ─────────────────────────────────────────────── */

interface Reminder {
  /** Epoch ms at which it reaches zero. */
  fireAt: number;
  /** Reached zero; the alert shows until dismissed. */
  due: boolean;
}

const reminders = new Map<string, Reminder>();
const timers = new Map<string, number>();
const listeners = new Set<() => void>();

function publish() {
  for (const fn of listeners) fn();
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** The storage key doubles as the store key: one reminder per Fan. */
function reminderKey(accountId: string | null, fanId: FanId | null): string | null {
  return accountId && fanId != null ? `chatterly:timed-reminder:${accountId}:${fanId}` : null;
}

/** Zero: show the alert; an OS notification under the toaster's rule (the
 *  "OS notification when tab is unfocused" setting, and only while this window
 *  is unfocused; natively in the desktop app, in a browser only when already
 *  allowed, never asking); and the reminder sound when it is on (bell → Toast
 *  settings → Sounds). */
function fire(key: string, fireAt: number) {
  timers.delete(key);
  reminders.set(key, { fireAt, due: true });
  publish();
  const settings = readNotifSettings();
  if (settings.osPing && !document.hasFocus()) void osNotify({ id: key, title: "Timed reminder", body: "Time's up" });
  if (settings.sounds.reminder.on) playAlertOnce(key, settings.sounds.reminder.sound);
}

/** Hold `fireAt` for `key`, firing now when it has already passed. */
function arm(key: string, fireAt: number) {
  window.clearTimeout(timers.get(key));
  const left = fireAt - Date.now();
  if (left <= 0) {
    fire(key, fireAt);
    return;
  }
  reminders.set(key, { fireAt, due: false });
  timers.set(key, window.setTimeout(() => fire(key, fireAt), left));
  publish();
}

function startReminder(key: string, minutes: number) {
  const fireAt = Date.now() + minutes * 60_000;
  try { window.localStorage.setItem(key, String(fireAt)); } catch { /* quota — silent */ }
  arm(key, fireAt);
}

/** Cancel a running reminder or dismiss its alert; either way it is gone,
 *  from storage too, so an expired one alerts once. */
function clearReminder(key: string) {
  window.clearTimeout(timers.get(key));
  timers.delete(key);
  reminders.delete(key);
  try { window.localStorage.removeItem(key); } catch { /* storage blocked — silent */ }
  publish();
}

/** After a reload the store is empty: pick the fire time back up from
 *  storage the first time this Fan's Thread opens. */
function restoreReminder(key: string) {
  if (reminders.has(key)) return;
  let fireAt = 0;
  try { fireAt = Number(window.localStorage.getItem(key)); } catch { /* storage blocked — silent */ }
  if (fireAt > 0) arm(key, fireAt);
}

function useReminder(key: string | null): Reminder | undefined {
  useEffect(() => { if (key) restoreReminder(key); }, [key]);
  return useSyncExternalStore(
    subscribe,
    () => (key ? reminders.get(key) : undefined),
    () => undefined,
  );
}

/** m:ss, rounding up so a fresh 1-minute reminder reads 1:00. */
function formatLeft(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** "m:ss" left until `fireAt`, read from the clock once a second. Keyed by
 *  the fire time, so a new reminder starts from a fresh reading. */
function Countdown({ fireAt }: { fireAt: number }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  return formatLeft(fireAt - now);
}

/** A notice in the Composer's notice area (`MP.ours.Composer.notice`), one line. */
const NOTICE = cn(MP.ours.Composer.notice, "flex items-center");

/** The Composer's notice-area strip for this Fan's reminder: "Timed reminder
 *  · m:ss" with ✕ to cancel while it runs, then a `role="alert"` strip with
 *  ✕ to dismiss. Renders nothing without a reminder. */
export function TimedReminderNotice({
  accountId, fanId,
}: { accountId: string | null; fanId: FanId | null }) {
  const key = reminderKey(accountId, fanId);
  const reminder = useReminder(key);

  if (!key || !reminder) return null;
  if (reminder.due) {
    return (
      <div role="alert" className={cn(NOTICE, "bg-warn/10 border-warn/40 text-warn")}>
        <span className="flex-1 font-medium">Timed reminder — time&apos;s up</span>
        <button
          type="button"
          onClick={() => clearReminder(key)}
          aria-label="Dismiss"
          title="Dismiss"
          className="text-fg-dim hover:text-fg"
        >
          ✕
        </button>
      </div>
    );
  }
  return (
    <div className={cn(NOTICE, "bg-accent/10 border-accent/30 text-[var(--inf-accent-text,var(--color-accent))]")}>
      <span className="flex-1">Timed reminder · <Countdown key={reminder.fireAt} fireAt={reminder.fireAt} /></span>
      <button
        type="button"
        onClick={() => clearReminder(key)}
        aria-label="Cancel timed reminder"
        title="Cancel timed reminder"
        className="text-fg-dim hover:text-fg"
      >
        ✕
      </button>
    </div>
  );
}

/* ── the ⏱ popover ────────────────────────────────────────────────────── */

export interface TimedMessagePopoverProps {
  /** The Fan the Timed reminder is for; without both, it cannot start. */
  accountId: string | null;
  fanId: FanId | null;
  /** The draft can be sent now (not empty, chat not blocked, not disabled). */
  canSend: boolean;
  /** OnlyFans refuses this chat. */
  blocked: boolean;
  /** Why the Composer holds Send (an upload in flight or failed), shown on
   *  "Start" in place of the generic empty-draft line. */
  sendBlockedReason?: string | null;
  /** GIFs on the draft. */
  gifCount: number;
  disabled?: boolean;
  onStart: (minutes: number) => void;
  /** Schedule mode on, "at" = now plus `minutes`; never sends. */
  onPreset: (minutes: number) => void;
}

const PRESET_MINUTES = [5, 10, 15, 30, 60];

/** Whole minutes from 1 to 60 (§3.3:213), else null. */
function parseMinutes(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const n = Number(value);
  return n >= 1 && n <= 60 ? n : null;
}

/** Why "Start" is disabled, or null when it is not. */
function whyNot(
  { canSend, blocked, sendBlockedReason, gifCount }: TimedMessagePopoverProps,
  minutes: number | null,
): string | null {
  if (blocked) return "Sending is disabled for this chat";
  if (sendBlockedReason) return sendBlockedReason;
  if (!canSend) return "Type a message or attach something first";
  if (minutes == null) return "Enter whole minutes from 1 to 60";
  if (gifCount > 1) return "A Timed message carries one GIF: remove the others";
  // Our executor queue carries a GIF; OnlyFans' queue, past
  // EXECUTOR_MAX_MINUTES, does not (spec, Contracts).
  if (gifCount === 1 && minutes > EXECUTOR_MAX_MINUTES) {
    return `A GIF can be timed ${EXECUTOR_MAX_MINUTES} minutes out at most`;
  }
  return null;
}

type Tab = "message" | "reminder";

export function TimedMessagePopover(props: TimedMessagePopoverProps) {
  const { accountId, fanId, disabled, onStart, onPreset } = props;
  const { open, setOpen, rootRef } = usePopover();
  const id = useId();
  const [tab, setTab] = useState<Tab>("message");
  const [value, setValue] = useState("5");
  const minutes = parseMinutes(value);
  const reminderAt = reminderKey(accountId, fanId);
  const isMessage = tab === "message";
  const reason = isMessage
    ? whyNot(props, minutes)
    : !reminderAt
      ? "Open a Fan's chat to set a reminder"
      : minutes == null ? "Enter whole minutes from 1 to 60" : null;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label="Timed message"
        title="Timed message"
        className={cn(ROW_ICON, open ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg")}
      >
        <AlarmClock aria-hidden className={MP.composer.buttonRowIcon} />
      </button>
      {open && (
        <section id={id} aria-label="Timed message" className={POP}>
          <div role="tablist" aria-label="Timed" className={cn(POP_HEAD, MP.ours.TimedMessagePopover.tabs, "flex")}>
            {(["message", "reminder"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={cn("uppercase", tab === t ? "text-[var(--inf-accent-text,var(--color-accent))]" : "hover:text-fg")}
              >
                {t === "message" ? "Timed message" : "Timed reminder"}
              </button>
            ))}
          </div>
          <div role="tabpanel" className={POP_ROW}>
            <label className={cn(MP.ours.TimedMessagePopover.label, "flex items-center text-fg-dim")}>
              {isMessage ? "Send in" : "Remind in"}
              <input
                type="text"
                inputMode="numeric"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-label="Minutes"
                className={cn(FIELD, MP.ours.TimedMessagePopover.minutes)}
              />
              min
            </label>
            <button
              type="button"
              onClick={() => {
                if (minutes == null) return;
                setOpen(false);
                if (isMessage) onStart(minutes);
                else if (reminderAt) startReminder(reminderAt, minutes);
              }}
              disabled={reason != null}
              title={reason ?? (isMessage
                ? `Send this message in ${minutes} min`
                : `Remind me about this Fan in ${minutes} min`)}
              className={cn(POP_PRIMARY, "disabled:bg-[var(--inf-idle-fill,var(--color-bg-elev-2))] ml-auto")}
            >
              Start
            </button>
          </div>
          {isMessage && (
            <div role="group" aria-label="Send at presets">
              <div className={POP_HEAD}>Send at</div>
              <div className={cn(POP_ROW, "flex-wrap")}>
                {PRESET_MINUTES.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      onPreset(m);
                    }}
                    className="text-xs px-2 py-1 rounded-md border border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1"
                  >
                    +{m}m
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

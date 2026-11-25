"use client";


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


interface Reminder {
  fireAt: number;
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

function reminderKey(accountId: string | null, fanId: FanId | null): string | null {
  return accountId && fanId != null ? `chatterly:timed-reminder:${accountId}:${fanId}` : null;
}

function fire(key: string, fireAt: number) {
  timers.delete(key);
  reminders.set(key, { fireAt, due: true });
  publish();
  const settings = readNotifSettings();
  if (settings.osPing && !document.hasFocus()) void osNotify({ id: key, title: "Timed reminder", body: "Time's up" });
  if (settings.sounds.reminder.on) playAlertOnce(key, settings.sounds.reminder.sound);
}

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
  try { window.localStorage.setItem(key, String(fireAt)); } catch { }
  arm(key, fireAt);
}

// Also removed from storage so an expired reminder alerts once.
function clearReminder(key: string) {
  window.clearTimeout(timers.get(key));
  timers.delete(key);
  reminders.delete(key);
  try { window.localStorage.removeItem(key); } catch { }
  publish();
}

function restoreReminder(key: string) {
  if (reminders.has(key)) return;
  let fireAt = 0;
  try { fireAt = Number(window.localStorage.getItem(key)); } catch { }
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

function formatLeft(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function Countdown({ fireAt }: { fireAt: number }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  return formatLeft(fireAt - now);
}

const NOTICE = cn(MP.ours.Composer.notice, "flex items-center");

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


export interface TimedMessagePopoverProps {
  accountId: string | null;
  fanId: FanId | null;
  canSend: boolean;
  blocked: boolean;
  sendBlockedReason?: string | null;
  gifCount: number;
  disabled?: boolean;
  onStart: (minutes: number) => void;
  onPreset: (minutes: number) => void;
}

const PRESET_MINUTES = [5, 10, 15, 30, 60];

function parseMinutes(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const n = Number(value);
  return n >= 1 && n <= 60 ? n : null;
}

function whyNot(
  { canSend, blocked, sendBlockedReason, gifCount }: TimedMessagePopoverProps,
  minutes: number | null,
): string | null {
  if (blocked) return "Sending is disabled for this chat";
  if (sendBlockedReason) return sendBlockedReason;
  if (!canSend) return "Type a message or attach something first";
  if (minutes == null) return "Enter whole minutes from 1 to 60";
  if (gifCount > 1) return "A Timed message carries one GIF: remove the others";
  // Our executor queue carries a GIF; OF's queue, past EXECUTOR_MAX_MINUTES, does not.
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
                    title={`Send in ${m} min`}
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

"use client";

/**
 * NotificationToaster — listens to OF's SSE `toasts` event, renders a
 * transient toast top-right, and bumps the bell badge by 1 per arrival.
 *
 * Badge ownership lives in NotificationBell (tab-local counter). This
 * component only fires `chatterly:notif-arrived` events; the bell
 * subscribes and increments. No polling, no count diffing, no
 * cross-tab baseline — every tab starts at 0 and counts forward.
 *
 * We still mirror each arrival into localStorage via appendNotifHistory
 * so the bell dropdown can display likes / mentions that OF's own
 * /notifications endpoint drops.
 *
 * Two non-OF sources share the stack. The clock-in reminder
 * (docs/spec/phase-02-shifts-time-tracking.md, Clock-in reminder): for a
 * Chatter session it polls `GET /admin/shifts/me` every minute and shows
 * "Your shift on <Creator> has started." once per (shift_id,
 * occurrence_start), keyed in localStorage, with a "Clock in" action that
 * clocks in at once through `useClock` (or opens `ClockDialog` for a chatter
 * in two Agencies, who names a Creator). And the app's one-line notices
 * (`lib/notices`), such as the clock's "Clock in successful" and a chatter's
 * access changes (`useAccessChangeNotices`). In-app only: no
 * email, push or OS notification.
 */

import { useEffect } from "react";

import ClockDialog from "@/components/shifts/ClockDialog";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { useAccessChangeNotices } from "@/hooks/useAccessChangeNotices";
import { proxyImage } from "@/lib/mediaUrl";
import { onNotice } from "@/lib/notices";
import { onNotificationClick } from "@/lib/notificationLink";
import { useClock, useMyShifts } from "@/lib/shifts";
import { labelFor, stickerFor } from "@/lib/notifText";
import { dispatchNotifCleared } from "@/lib/notifSettings";
import {
  TOAST_TTL_MS,
  dismissToast,
  pushToast,
  useToastStack,
  type Toast,
} from "./toastStore";
import { useNotificationDelta } from "./useNotificationDelta";

/** The SSE lanes (`useNotificationDelta`), as a leaf that renders nothing: a
 *  render boundary, so its scope/accounts/settings re-renders skip ToastStack. */
function NotificationDeltaPoller() {
  useNotificationDelta();
  return null;
}

function ToastCard({ t }: { t: Toast }) {
  const avatar = proxyImage(t.user?.avatar ?? null, t.accountId);
  const ring = t.bubble
    ? "ring-2 ring-accent shadow-[0_0_24px_-4px_var(--color-accent)]"
    : "ring-1 ring-border";
  const sticker = t.bubble ? "text-base" : "text-xs";
  const body = (
    <div
      className={
        "pointer-events-auto w-auto sm:w-[320px] bg-panel rounded-lg overflow-hidden flex items-start gap-2.5 p-2.5 " +
        ring
      }
    >
      <div className="w-9 h-9 rounded-full bg-bg-elev-1 overflow-hidden shrink-0 grid place-items-center relative">
        {avatar ? (
          <img src={avatar} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
        ) : (
          <span className="text-[11px] text-fg-dim">
            {(t.user?.name || t.user?.username || "?").slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className={`absolute -bottom-1 -right-1 ${sticker}`} aria-hidden>
          {stickerFor(t.typeKey)}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] text-fg leading-snug">
          {t.user?.name && <span className="font-medium">{t.user.name} </span>}
          <span className="text-fg-dim">{t.text}</span>
        </div>
        <div className="text-[10px] text-fg-dim mt-0.5 flex items-center justify-between gap-2">
          <span>{labelFor(t.typeKey, t.rawType)}</span>
          {t.href && (
            <span className="text-fg-dim/80 hover:text-fg underline underline-offset-2">
              Open chat ↗
            </span>
          )}
        </div>
      </div>
      {t.action && (
        <button
          type="button"
          onClick={() => { t.action?.run(); dismissToast(t.accountId, t.id); }}
          className="text-[11px] px-2 h-10 sm:h-6 rounded border border-border hover:bg-bg-elev-1 shrink-0"
        >
          {t.action.label}
        </button>
      )}
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); dismissToast(t.accountId, t.id); }}
        className="text-fg-dim hover:text-fg text-[11px] w-10 h-10 sm:w-5 sm:h-5 grid place-items-center rounded hover:bg-bg-elev-1"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
  if (t.href) {
    const href = t.href;
    return (
      <a
        href={href}
        className="block animate-toast-in"
        onClick={(e) => {
          onNotificationClick(e, href);
          dispatchNotifCleared();
          dismissToast(t.accountId, t.id);
        }}
      >
        {body}
      </a>
    );
  }
  return <div className="animate-toast-in">{body}</div>;
}

function ToastStack() {
  const toasts = useToastStack();
  if (toasts.length === 0) return null;
  return (
    <div className="fixed top-[var(--chrome-top)] left-2 right-2 sm:left-auto sm:right-3 z-[60] flex flex-col gap-2 pointer-events-none [&>*:nth-child(n+3)]:hidden sm:[&>*:nth-child(n+3)]:block">
      {toasts.slice().reverse().map((t) => (
        <ToastCard key={`${t.accountId ?? "app"}:${t.id}`} t={t} />
      ))}
    </div>
  );
}

const REMINDED_KEY = "chatterly:shift-reminders:v1";
const MAX_REMINDED = 200;

/** Atomically claim a reminder key: false = already shown in this browser
 *  (persisted, so a reload does not repeat it), true = now marked shown.
 *  Keeps the newest MAX_REMINDED keys. Keys carry the chatter id, so two
 *  chatters sharing a browser are each reminded. */
function claimReminder(key: string): boolean {
  let seen: string[] = [];
  try {
    const raw = JSON.parse(window.localStorage.getItem(REMINDED_KEY) ?? "[]");
    if (Array.isArray(raw)) seen = raw.filter((k): k is string => typeof k === "string");
  } catch { /* unreadable: start over */ }
  if (seen.includes(key)) return false;
  try {
    window.localStorage.setItem(REMINDED_KEY, JSON.stringify([...seen, key].slice(-MAX_REMINDED)));
  } catch { /* storage full or blocked: the toast still shows once in this tab */ }
  return true;
}

/**
 * The clock-in reminder: a Chatter session's `GET /admin/shifts/me` poll
 * (the Relay decides when `reminder` is set), one toast per occurrence.
 *
 * ASSUMPTION: the reminder toast ignores the notification Settings toggles
 * (they are per OF notification type) and does not bump the bell badge or
 * enter its history; the agency's `clock_in_reminder` is its only switch. It
 * keeps the stack's usual 8-second lifetime. Rung 3 for the lifetime, rung 5
 * for the rest. Overturned if the reminder must honour the master toggle or
 * stay until dismissed.
 */
function ClockInReminder() {
  const user = useOptionalUser()?.user ?? null;
  const chatter = useOptionalChatter()?.chatter ?? null;
  const me = useMyShifts(!user && !!chatter);
  const clock = useClock(!user && !!chatter);
  // Stable, and reads the clock as it is when the toast's button runs.
  const act = clock.act;
  const reminder = me.data?.reminder ?? null;
  const accounts = me.data?.accounts;
  const chatterId = chatter?.chatter_id;

  useEffect(() => {
    if (!reminder || !chatterId) return;
    const key = `${chatterId}:${reminder.shift_id}:${reminder.occurrence_start}`;
    if (!claimReminder(key)) return;
    const creator = accounts?.find((a) => a.account_id === reminder.account_id)?.display_name
      ?? reminder.account_id;
    pushToast({
      id: `shift-reminder:${key}`,
      accountId: reminder.account_id,
      typeKey: null,
      rawType: "Shift reminder",
      user: null,
      text: `Your shift on ${creator} has started.`,
      createdAt: Date.now(),
      bubble: false,
      href: null,
      expiresAt: Date.now() + TOAST_TTL_MS,
      action: { label: "Clock in", run: () => void act("in") },
    });
  }, [reminder, accounts, chatterId, act]);

  return clock.picking ? <ClockDialog onClose={clock.closePicker} /> : null;
}

/** `lib/notices`' one-line notices as cards in the stack, with the usual lifetime. */
function NoticeBridge() {
  useEffect(() => onNotice((n) => pushToast({
    id: n.id,
    accountId: null,
    typeKey: null,
    rawType: n.label,
    user: null,
    text: n.text,
    createdAt: Date.now(),
    bubble: false,
    href: null,
    expiresAt: Date.now() + TOAST_TTL_MS,
  })), []);
  return null;
}

export function NotificationToaster() {
  // A chatter's "permissions updated" / "unassigned from" notices.
  useAccessChangeNotices();
  return (
    <>
      <NotificationDeltaPoller />
      <ClockInReminder />
      <NoticeBridge />
      <ToastStack />
    </>
  );
}

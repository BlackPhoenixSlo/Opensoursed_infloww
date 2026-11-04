"use client";

/**
 * OsPingSettings — the bell's "OS notification" row: the checkbox, Test and,
 * with Web Push live, "Send push in 8 s" (lock the phone, see it arrive).
 * Both taps are the gesture Web Push needs (lib/webPush `subscribePush`
 * calls `pushManager.subscribe` first, which asks the permission). Without
 * push (desktop app, dev build, no PushManager, nothing to push) Test shows
 * an in-page notification as before. A denied permission and an iPhone /
 * iPad tab (push only from the Home Screen app) get their own message.
 * `pushHintShown`: the bell's line while push is wanted but not live (a lazy
 * subscribe failed, or the permission was never asked).
 */

import { useState } from "react";

import { BRAND_NAME } from "@/lib/brand";
import { hasShellNotify, osNotify } from "@/lib/osNotify";
import { pushWanted } from "@/lib/pushPrefs";
import type { NotifSettings } from "@/lib/notifSettings";
import {
  iosTab,
  pushSupported,
  showViaWorker,
  subscribePush,
  testPush,
  unsubscribePush,
  usePushState,
  why,
  type PushState,
} from "@/lib/webPush";

export const PUSH_HINT = "Tap Test to enable lock-screen alerts";
export const DENIED_MSG = "✗ Notifications are blocked for this site: no OS alerts at all. " +
  `Allow them in the browser's site settings (iPhone / iPad: Settings > Notifications > ${BRAND_NAME}).`;
export const IOS_TAB_MSG = "✗ On iPhone / iPad, alerts need the app: Share > Add to Home Screen, " +
  "open it from there, then tap Test.";
const TEST_BODY = "If you see this in your OS tray, it works.";
const TEST_TAG = "chatterly-test";

const permission = (): NotificationPermission | null =>
  typeof Notification === "undefined" ? null : Notification.permission;

export function pushHintShown(settings: NotifSettings, push: PushState): boolean {
  return pushWanted(settings) && pushSupported() && push.id === null &&
    (push.failed !== null || permission() === "default");
}

/** The Test's message when push could not come up. */
export function pushFailMessage(reason: string, perm: NotificationPermission | null): string {
  return perm === "denied" ? DENIED_MSG : `✗ push unavailable: ${reason}, alerts only while open`;
}

/** The in-page notification (no push): the message to show. */
async function inPageTest(): Promise<string> {
  if (typeof Notification === "undefined") return "✗ This browser has no Notification API.";
  let perm = Notification.permission;
  if (perm === "default") {
    try {
      perm = await Notification.requestPermission();
    } catch {
      return "✗ requestPermission threw";
    }
  }
  if (perm === "denied") return DENIED_MSG;
  if (perm !== "granted") return `✗ Permission ${perm}. Open the browser's site settings → allow Notifications.`;
  try {
    new Notification(`${BRAND_NAME} test`, { body: TEST_BODY, tag: TEST_TAG });
    return "✓ Fired — check your OS tray.";
  } catch (err) {
    return "✗ new Notification threw: " + (err as Error).message;
  }
}

export function OsPingSettings({ settings, update }: {
  settings: NotifSettings;
  update: (patch: Partial<NotifSettings>) => void;
}) {
  // `sendable`: push came up from this Test, so the delayed-push link shows.
  const [test, setTest] = useState<{ msg: string; sendable?: boolean } | null>(null);
  const push = usePushState();

  const toggle = (on: boolean) => {
    update({ osPing: on });
    if (!on) {
      void unsubscribePush();
      return;
    }
    const next = { ...settings, osPing: true };
    if (pushSupported() && pushWanted(next)) {
      void subscribePush(next).catch(() => {}); // a failure shows the hint
    } else if (!hasShellNotify() && typeof Notification !== "undefined" && Notification.permission === "default") {
      void Notification.requestPermission().catch(() => {});
    }
  };

  const runTest = async () => {
    if (hasShellNotify()) {
      // The desktop app notifies natively: no web permission.
      setTest({ msg: "Sending to the desktop app…" });
      const ok = await osNotify({ id: `chatterly-test:${Date.now()}`, title: `${BRAND_NAME} test`, body: TEST_BODY });
      setTest({ msg: ok
        ? "✓ Handed to the OS — check your notifications."
        : `✗ The desktop app could not show it. Check the OS notification settings for ${BRAND_NAME}.` });
      return;
    }
    if (iosTab()) {
      setTest({ msg: IOS_TAB_MSG });
      return;
    }
    if (!pushSupported() || !pushWanted(settings)) {
      setTest({ msg: await inPageTest() });
      return;
    }
    setTest({ msg: "Turning push on…" });
    try {
      await subscribePush(settings); // first: inside the tap, it asks the permission
      await showViaWorker(`${BRAND_NAME} test`, { body: TEST_BODY, tag: TEST_TAG });
      setTest({ msg: "✓ Push on: lock screen alerts active", sendable: true });
    } catch (e) {
      const perm = permission();
      if (perm === "granted") await inPageTest();
      setTest({ msg: pushFailMessage(why(e), perm) });
    }
  };

  const sendLater = async () => {
    setTest({ msg: "Push in 8 s: lock your phone now." });
    try {
      const r = await testPush(8);
      if (r?.status && r.status >= 300) setTest({ msg: `✗ the push service said ${r.status}${r.reason ? `: ${r.reason}` : ""}` });
    } catch (e) {
      setTest({ msg: `✗ test push failed: ${why(e)}` });
    }
  };

  return (
    <>
      <div className="mt-2 flex items-center justify-between gap-2">
        <label className="flex items-center gap-1.5 text-[11px] text-fg-dim cursor-pointer">
          <input
            type="checkbox"
            checked={settings.osPing}
            onChange={(e) => toggle(e.target.checked)}
            disabled={!settings.enabled}
          />
          OS notification when tab is unfocused
        </label>
        <button
          type="button"
          onMouseDown={(e) => { e.stopPropagation(); }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            void runTest();
          }}
          className="px-2 py-0.5 text-[11px] rounded border border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1"
          title="Verify OS notifications are working"
        >
          Test
        </button>
      </div>
      {(test || pushHintShown(settings, push)) && (
        <div className="mt-1.5 text-[10px] text-fg-dim leading-snug">
          {test?.msg ?? PUSH_HINT}
          {test?.sendable && push.id && (
            <>
              {" "}
              <button
                type="button"
                onMouseDown={(e) => { e.stopPropagation(); }}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  void sendLater();
                }}
                className="underline underline-offset-2 hover:text-fg"
              >
                Send push in 8 s, lock your phone
              </button>
            </>
          )}
        </div>
      )}
    </>
  );
}

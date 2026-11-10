import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_NOTIF_SETTINGS, readNotifSettings, writeNotifSettings } from "./notifSettings";

const KEY = "chatterly:notif-settings:v1";
const OLD_SAVE = {
  ...DEFAULT_NOTIF_SETTINGS, enabled: false,
  toast: { ...DEFAULT_NOTIF_SETTINGS.toast, message: false, subscribed: false, tip: false, commented: true },
};

afterEach(() => window.localStorage.clear());

describe("notif settings defaults round 2", () => {
  it.each<[string, unknown, Record<string, boolean>, boolean]>([
    ["nothing saved → defaults", null, { message: true, purchases: true, tip: true, subscribed: true, commented: false }, true],
    ["saved before round 2 → the four on once, other choices kept", OLD_SAVE,
      { message: true, purchases: true, tip: true, subscribed: true, commented: true }, true],
    ["saved in round 2 → the user's choice stays", { ...OLD_SAVE, defaultsRound: 2 },
      { message: false, purchases: true, tip: false, subscribed: false, commented: true }, false],
  ])("%s", (_n, stored, toast, enabled) => {
    if (stored) window.localStorage.setItem(KEY, JSON.stringify(stored));
    const s = readNotifSettings();
    expect(s.enabled).toBe(enabled);
    expect(s.toast).toMatchObject(toast);
  });

  it("a save after the migration keeps a turned-off toast off", () => {
    window.localStorage.setItem(KEY, JSON.stringify(OLD_SAVE));
    const s = readNotifSettings();
    writeNotifSettings({ ...s, toast: { ...s.toast, message: false } });
    expect(readNotifSettings().toast.message).toBe(false);
  });
});

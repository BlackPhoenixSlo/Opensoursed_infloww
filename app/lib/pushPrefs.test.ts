import { describe, expect, it } from "vitest";

import { DEFAULT_NOTIF_SETTINGS, type NotifSettings } from "@/lib/notifSettings";
import { pushBody, pushTypes, pushWanted } from "@/lib/pushPrefs";

const s = (over: Partial<NotifSettings> = {}): NotifSettings => ({ ...DEFAULT_NOTIF_SETTINGS, ...over });

describe("pushPrefs", () => {
  it.each([
    // [label, settings, types]
    ["defaults: the money types", s(), ["purchases", "tip"]],
    ["master off", s({ enabled: false }), []],
    ["OS ping off", s({ osPing: false }), []],
    ["every toast off", s({ toast: { ...DEFAULT_NOTIF_SETTINGS.toast, purchases: false, tip: false } }), []],
    ["messages on, in NOTIF_TYPES order", s({ toast: { ...DEFAULT_NOTIF_SETTINGS.toast, message: true, favorited: true } }),
      ["message", "purchases", "tip", "favorited"]],
  ] as const)("%s", (_l, settings, types) => {
    expect(pushTypes(settings)).toEqual(types);
    expect(pushWanted(settings)).toBe(types.length > 0);
  });

  it("the body carries the types and the platform switches", () => {
    expect(pushBody(s({ platforms: { onlyfans: true, fansly: false } }))).toEqual({
      types: ["purchases", "tip"], platforms: { onlyfans: true, fansly: false },
    });
  });
});

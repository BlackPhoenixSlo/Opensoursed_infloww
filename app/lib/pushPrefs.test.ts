import { describe, expect, it } from "vitest";

import { DEFAULT_NOTIF_SETTINGS, type NotifSettings } from "@/lib/notifSettings";
import { pushBody, pushTypes, pushWanted } from "@/lib/pushPrefs";

const s = (over: Partial<NotifSettings> = {}): NotifSettings => ({ ...DEFAULT_NOTIF_SETTINGS, ...over });

describe("pushPrefs", () => {
  it.each([
    // [label, settings, types]
    ["defaults: messages, purchases, tips and subscribers", s(), ["message", "purchases", "tip", "subscribed"]],
    ["master off", s({ enabled: false }), []],
    ["OS ping off", s({ osPing: false }), []],
    ["every toast off", s({ toast: { message: false, purchases: false, tip: false, subscribed: false, mentioned: false, commented: false, favorited: false } }), []],
    ["likes enabled too, in NOTIF_TYPES order", s({ toast: { ...DEFAULT_NOTIF_SETTINGS.toast, favorited: true } }),
      ["message", "purchases", "tip", "subscribed", "favorited"]],
  ] as const)("%s", (_l, settings, types) => {
    expect(pushTypes(settings)).toEqual(types);
    expect(pushWanted(settings)).toBe(types.length > 0);
  });

  it("the body carries the types and the platform switches", () => {
    expect(pushBody(s({ platforms: { onlyfans: true, fansly: false } }))).toEqual({
      types: ["message", "purchases", "tip", "subscribed"], platforms: { onlyfans: true, fansly: false },
    });
  });
});

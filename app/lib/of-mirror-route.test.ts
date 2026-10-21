import { describe, expect, it } from "vitest";
import { mirrorPageOf, mirrorPageOfHref, mirrorPageOfPath, mirrorRedirectOf } from "./of-mirror-route";

describe("the mirrored page an OF Manager URL shows", () => {
  it("a section root shows its index sub: settings is OF's profile page, home its index file", () => {
    expect(mirrorPageOf("settings")?.key).toBe("settings/profile");
    expect(mirrorPageOf("home", [])?.key).toBe("home/index");
    expect(mirrorPageOf("settings", ["subscription", "promotion-campaign"])).toEqual({ key: "settings/subscription/promotion-campaign", title: "Subscription and Promotions" });
    expect(mirrorPageOf("settings", ["no-such-page"])).toBeNull();
    expect(mirrorPageOf("no-such-section")).toBeNull();
  });

  it("an href's page: its query and hash dropped; none outside /of-manager", () => {
    expect(mirrorPageOfHref("/of-manager/settings")).toBe("settings/profile");
    expect(mirrorPageOfHref("/of-manager/settings?x=1#promotion")).toBe("settings/profile");
    expect(mirrorPageOfHref("/of-manager/messages/chat?chat=1")).toBe("messages/chat");
    expect(mirrorPageOfHref("/of-manager/home/")).toBe("home/index");
    expect(mirrorPageOfHref("")).toBeNull();
    expect(mirrorPageOfHref("/settings")).toBeNull();
  });

  it("Following's Users page and its chips open Collections' Following list; its Posts tab and every other page are their own (U6)", () => {
    for (const chip of [[], ["active"], ["expired"], ["attention"]])
      expect(mirrorRedirectOf("collections", ["user-lists", "subscriptions", ...chip])).toBe("/of-manager/collections/user-lists/list?list=following");
    expect(mirrorRedirectOf("collections", ["user-lists", "subscriptions", "posts"])).toBeNull();
    expect(mirrorRedirectOf("collections", ["user-lists", "list"])).toBeNull();
    expect(mirrorRedirectOf("collections")).toBeNull();
    expect(mirrorPageOfHref("/of-manager/collections/user-lists/list?list=following")).toBe("collections/user-lists/list");
  });

  it("Following's New message (sendlist-following) and its tabs open New message's own: Following ticked, or the tab (U6)", () => {
    expect(mirrorRedirectOf("messages", ["send", "sendlist-following"])).toBe("/of-manager/messages/send?to=following");
    expect(mirrorRedirectOf("messages", ["send", "list-users"])).toBe("/of-manager/messages/send?list=users");
    expect(mirrorRedirectOf("messages", ["send", "list-exclude"])).toBe("/of-manager/messages/send?list=exclude");
    expect(mirrorRedirectOf("messages", ["send"])).toBeNull();
  });

  it("the promotion and bundle dialogs' captured dropdown pages open their dialog, whose selects open OF's list", () => {
    const at = (page: string) => mirrorRedirectOf("settings", ["subscription", "promotion-campaign", page]);
    for (const n of [0, 1, 2]) expect(at(`state-promo-dropdowns-${n}`)).toBe("/of-manager/settings/subscription/promotion-campaign/modal-1");
    for (const k of ["discount", "duration"]) expect(at(`state-bundle-${k}-dropdown`)).toBe("/of-manager/settings/subscription/promotion-campaign/modal-2");
    expect(at("modal-2")).toBeNull();
  });

  it("a mirror document's page: its key under of-mirror/pages; none for about:blank", () => {
    expect(mirrorPageOfPath("/of-mirror/pages/settings/subscription/promotion-campaign.html")).toBe("settings/subscription/promotion-campaign");
    expect(mirrorPageOfPath("blank")).toBeNull();
    expect(mirrorPageOfPath("/of-manager/settings")).toBeNull();
  });
});

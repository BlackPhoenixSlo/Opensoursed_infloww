import { describe, expect, it } from "vitest";
import { mirrorPageOf, mirrorPageOfHref, mirrorPageOfPath } from "./of-mirror-route";

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

  it("a mirror document's page: its key under of-mirror/pages; none for about:blank", () => {
    expect(mirrorPageOfPath("/of-mirror/pages/settings/subscription/promotion-campaign.html")).toBe("settings/subscription/promotion-campaign");
    expect(mirrorPageOfPath("blank")).toBeNull();
    expect(mirrorPageOfPath("/of-manager/settings")).toBeNull();
  });
});

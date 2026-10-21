/**
 * PlatformSwitches — Your Preferences' per-platform switches (roadmap 8.10):
 * OnlyFans display sync and notifications per platform, this browser's own
 * localStorage choices, on by default and applied without the blob's Save.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";

import PlatformSwitches from "@/components/settings/PlatformSwitches";
import { readNotifSettings } from "@/lib/notifSettings";
import { readOfDisplaySync } from "@/lib/ofMirrorTheme";

const section = (title: string) => screen.getByRole("heading", { name: title }).closest("section")!;
const sw = (title: string, name: string) => within(section(title)).getByRole("switch", { name });

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); localStorage.clear(); });

describe("PlatformSwitches", () => {
  it("shows every switch on by default, including over settings saved before the platform switches", () => {
    localStorage.setItem("chatterly:notif-settings:v1", JSON.stringify({ enabled: true, osPing: false }));
    render(<PlatformSwitches />);
    expect(sw("Synchronize platform display settings", "OnlyFans").getAttribute("aria-checked")).toBe("true");
    for (const name of ["OnlyFans", "Fansly"]) {
      expect(sw("Platform notifications", name).getAttribute("aria-checked")).toBe("true");
    }
    expect(within(section("Synchronize platform display settings")).queryByRole("switch", { name: "Fansly" })).toBeNull();
    expect(readNotifSettings().osPing).toBe(false); // the old blob's other keys kept
  });

  it("server-renders the defaults whatever is stored, so hydration matches", () => {
    localStorage.setItem("chatterly:notif-settings:v1", JSON.stringify({ platforms: { onlyfans: false, fansly: false } }));
    const html = renderToString(<PlatformSwitches />);
    expect(html).not.toContain('aria-checked="false"');
  });

  it("stores each switch at once", () => {
    render(<PlatformSwitches />);
    fireEvent.click(sw("Synchronize platform display settings", "OnlyFans"));
    expect(readOfDisplaySync()).toBe(false);
    expect(sw("Synchronize platform display settings", "OnlyFans").getAttribute("aria-checked")).toBe("false");

    fireEvent.click(sw("Platform notifications", "Fansly"));
    expect(readNotifSettings().platforms).toEqual({ onlyfans: true, fansly: false });
    expect(sw("Platform notifications", "Fansly").getAttribute("aria-checked")).toBe("false");
  });
});

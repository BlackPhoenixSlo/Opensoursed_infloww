import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/plugins.generated.register", () => ({ PLUGINS: [] }));

import { FANSLY_MIRROR_SECTIONS, type FanslyMirrorSection } from "@/lib/fansly-mirror-pages";
import { deniedPage, FANSLY_NAV, isDivider, isGroup, PERMISSION_PAGES } from "@/lib/nav";
import { fanslyRouteOf, firstFanslyPage, routableFanslyPages, withCreator } from "./fansly-mirror-route";

const TABLE: Record<string, FanslyMirrorSection> = {
  home: { index: "", pages: { "": "Home" } },
  settings: { index: "profile", pages: { profile: "Profile settings", privacy: "Privacy" } },
  scheduled: { index: "", pages: { "": "Scheduled", calendar: "Calendar" } },
  lists: { index: "", pages: { "": "Lists", list: "List" } },
  notifications: { index: "", pages: { "": "Notifications" } },
  statistics: { index: "", pages: { "": "Profile statistics", earnings: "Earnings" } },
};

const route = (section: string, path: string[] = [], creator: string | null = null) => fanslyRouteOf(section, path, creator, TABLE);

describe("the page a /fansly-manager URL shows", () => {
  it.each([
    ["scheduled", "Scheduled Posts"],
    ["lists", "Lists"],
    ["notifications", "Notifications"],
    ["earning-statistics", "Earning Statistics"],
  ])("the bare %s is its Built page", (section, label) => {
    expect(route(section)).toEqual({ kind: "built", href: `/fansly-manager/${section}`, label });
  });

  it("a subpage under a Built section is the mirror page", () => {
    expect(route("lists", ["list"])).toEqual({ kind: "mirror", key: "lists/list", label: "Lists", title: "Lists: List", src: "/fansly-mirror/pages/lists/list.html" });
    expect(route("scheduled", ["calendar"])).toEqual({ kind: "mirror", key: "scheduled/calendar", label: "Scheduled Posts", title: "Scheduled Posts: Calendar", src: "/fansly-mirror/pages/scheduled/calendar.html" });
  });

  it("an empty path is the section's index sub, titled '<nav label>: <page title>'", () => {
    expect(route("home")).toEqual({ kind: "mirror", key: "home/index", label: "Homepage", title: "Homepage: Home", src: "/fansly-mirror/pages/home/index.html" });
    expect(route("settings")).toEqual({ kind: "mirror", key: "settings/profile", label: "Settings", title: "Settings: Profile settings", src: "/fansly-mirror/pages/settings/profile.html" });
    expect(route("settings", ["privacy"])?.kind).toBe("mirror");
  });

  it.each([
    ["an unknown section", "nope", []],
    ["an unknown sub", "home", ["nope"]],
    ["a prototype section", "__proto__", []],
    ["a prototype sub", "home", ["constructor"]],
    ["a constructor section", "constructor", []],
    ["a path under Earning Statistics", "earning-statistics", ["x"]],
    ["a table section with no nav entry", "orphan", []],
  ])("%s is a 404", (_, section, path) => {
    expect(fanslyRouteOf(section, path, null, { ...TABLE, orphan: { index: "", pages: { "": "Orphan" } } })).toBeNull();
  });

  it("the mirror's earnings page redirects to Built Earning Statistics, keeping the picked creator", () => {
    expect(route("statistics", ["earnings"])).toEqual({ kind: "redirect", to: "/fansly-manager/earning-statistics" });
    expect(route("statistics", ["earnings"], "B")).toEqual({ kind: "redirect", to: "/fansly-manager/earning-statistics?creator=B" });
    expect(fanslyRouteOf("statistics", ["earnings"], "B")).toEqual({ kind: "redirect", to: "/fansly-manager/earning-statistics?creator=B" });
    expect(route("statistics", ["earnings", "x"])).toBeNull();
  });

  it("the redirect's target grant decides: Statistics alone is denied it, Creator reports alone opens it", () => {
    const to = (route("statistics", ["earnings"], "B") as { to: string }).to.split("?")[0];
    expect(deniedPage(to, new Set(["/of-manager/statistics"]))).toBe("/analytics/creator-reports");
    expect(deniedPage(to, new Set(["/analytics/creator-reports"]))).toBeNull();
  });

  it("the committed table serves the mirror home and keeps the Built pages", () => {
    expect(fanslyRouteOf("home", [], null)).toMatchObject({ kind: "mirror", key: "home/index", src: "/fansly-mirror/pages/home/index.html" });
    expect(fanslyRouteOf("lists", [], "B")).toEqual({ kind: "built", href: "/fansly-manager/lists", label: "Lists" });
  });
});

describe("withCreator", () => {
  it.each([
    ["/fansly-manager/home", "B", "/fansly-manager/home?creator=B"],
    ["/fansly-manager/home?creator=A", "B", "/fansly-manager/home?creator=A"],
    ["/fansly-manager/lists/list?tab=2", "B", "/fansly-manager/lists/list?tab=2&creator=B"],
    ["/fansly-manager/settings#privacy", "B", "/fansly-manager/settings?creator=B#privacy"],
    ["/fansly-manager/settings?tab=2#privacy", "a b", "/fansly-manager/settings?tab=2&creator=a%20b#privacy"],
    ["/fansly-manager/home?tab=2#x", null, "/fansly-manager/home?tab=2#x"],
  ])("%s with %s is %s", (href, creator, out) => {
    expect(withCreator(href, creator)).toBe(out);
  });
});

describe("firstFanslyPage", () => {
  const on = { fansly_manager: true, leak_tracker: false };
  it("flag off: none", () => {
    expect(firstFanslyPage({ chatterOnly: false, grantedPages: null })).toBeNull();
    expect(firstFanslyPage({ chatterOnly: false, grantedPages: null, flags: { fansly_manager: false, leak_tracker: false } })).toBeNull();
  });

  it("an owner lands on Homepage", () => {
    expect(firstFanslyPage({ chatterOnly: false, grantedPages: null, flags: on })).toBe("/fansly-manager/home");
  });

  it("a role without OnlyFans Home lands on the next entry it allows", () => {
    const noHome = new Set([...PERMISSION_PAGES].filter((p) => p !== "/of-manager/home"));
    expect(firstFanslyPage({ chatterOnly: true, grantedPages: noHome, flags: on })).toBe("/fansly-manager/profile");
    expect(firstFanslyPage({ chatterOnly: true, grantedPages: new Set(["/of-manager/notifications"]), flags: on })).toBe("/fansly-manager/notifications");
    expect(firstFanslyPage({ chatterOnly: true, grantedPages: new Set(["/messages-pro"]), flags: on })).toBeNull();
  });
});

describe("routableFanslyPages", () => {
  it("lists the table's mirror pages, never a landing a Built page shadows", () => {
    expect(routableFanslyPages(TABLE).sort()).toEqual(["home/index", "lists/list", "scheduled/calendar", "settings/privacy", "settings/profile", "statistics/index"]);
    const real = routableFanslyPages();
    expect(real).toContain("home/index");
    expect(real.filter((k) => ["scheduled/index", "lists/index", "notifications/index", "statistics/earnings"].includes(k))).toEqual([]);
  });
});

describe("the Built sections' raw landings", () => {
  const dir = path.join(process.cwd(), "public/fansly-mirror/pages");
  it.skipIf(!existsSync(dir))("exist under their mirror keys and nothing points at them", () => {
    const keys = [
      ...["scheduled", "lists", "notifications"].map((s) => `${s}/${FANSLY_MIRROR_SECTIONS[s]?.index || "index"}`),
      "statistics/earnings",
    ];
    const raw = keys.map((k) => `/fansly-mirror/pages/${k}.html`);
    expect(keys.filter((k) => !existsSync(path.join(dir, `${k}.html`)))).toEqual([]);
    expect(routableFanslyPages().filter((k) => keys.includes(k))).toEqual([]);
    const hrefs = FANSLY_NAV.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n])).map((l) => l.href);
    expect(hrefs.filter((h) => h.startsWith("/fansly-mirror/"))).toEqual([]);
    const to = fanslyRouteOf("statistics", ["earnings"], null);
    expect(to?.kind === "redirect" && raw.includes(to.to)).toBe(false);
    const files = (readdirSync(dir, { recursive: true }) as string[]).filter((f) => f.endsWith(".html"));
    const linking = files.filter((f) => raw.some((r) => readFileSync(path.join(dir, f), "utf8").includes(`"${r}`)));
    expect(linking).toEqual([]);
  });
});

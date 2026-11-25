import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER } from "@/lib/nav";
import { MESSAGE_DASHBOARD_TABS, SMART_MESSAGES_TABS } from "@/lib/pageTabs";

import { BARE, findPaths } from "./answerLinks";
import { openablePages } from "./prepass";

const ALL = openablePages({ chatterOnly: false, grantedPages: null });

function only(text: string) {
  const hits = findPaths(text, ALL);
  expect(hits.length).toBeLessThanOrEqual(1);
  if (hits.length === 0) return null;
  return { href: hits[0].href, text: text.slice(hits[0].start, hits[0].end) };
}

describe("findPaths", () => {
  it("resolves a two-segment growth path", () => {
    expect(only("In Growth → Auto-follow, set the switch.")).toEqual({
      href: "/growth/auto-follow",
      text: "Growth → Auto-follow",
    });
  });

  it("resolves a tab two arrows down", () => {
    expect(only("Open Analytics → Message dashboard → Customs to clear it.")).toEqual({
      href: "/analytics/message-dashboard?tab=customs",
      text: "Analytics → Message dashboard → Customs",
    });
  });

  it("walks through a step it cannot name when another arrow follows", () => {
    expect(only("Growth → Smart Messages → Mass Messages → OF mass messages → the Auto-unsend card")).toEqual({
      href: "/growth/smart-messages?tab=mass#go=OF+mass+messages&go=the+Auto-unsend+card",
      text: "Growth → Smart Messages → Mass Messages → OF mass messages",
    });
    expect(only("Messages Pro → + → Mass message")).toEqual({
      href: "/messages-pro#go=Mass+message",
      text: "Messages Pro → +",
    });
  });

  it("resolves a Settings page", () => {
    expect(only("Set it in Settings → AI keys (owner only).")).toEqual({
      href: "/settings/ai-keys",
      text: "Settings → AI keys",
    });
  });

  it("links the Settings page a sentence names without an arrow", () => {
    const text = "Settings has an Audit log page (owners only), but the manual doesn't describe it.";
    expect(findPaths(text, ALL).map((h) => [text.slice(h.start, h.end), h.href])).toEqual([
      ["Settings", "/settings/audit"],
      ["Audit log", "/settings/audit"],
    ]);
    const t2 = "In Settings, open Role Settings and tick it.";
    expect(findPaths(t2, ALL).map((h) => h.href)).toEqual(["/settings/roles", "/settings/roles"]);
    expect(only("Open Settings for it. Billing is elsewhere.")?.href).toBe("/settings");
    expect(findPaths("Settings, then Growth → Auto-follow, then AI keys", ALL).map((h) => h.href))
      .toEqual(["/settings", "/growth/auto-follow", "/settings/ai-keys"]);
  });

  it("links a page or tab of any section named in prose", () => {
    const hrefs = (t: string) => findPaths(t, ALL).map((h) => [t.slice(h.start, h.end), h.href]);
    expect(hrefs("Open Manage creators and press Add creator.")).toEqual([["Manage creators", "/creators"]]);
    expect(hrefs("In Message dashboard, open Tips.")).toEqual([
      ["Message dashboard", "/analytics/message-dashboard?tab=tips"],
      ["Tips", "/analytics/message-dashboard?tab=tips"],
    ]);
    expect(hrefs("Message dashboard → Customs owed lists them.")).toEqual([
      ["Message dashboard → Customs owed", "/analytics/message-dashboard?tab=customs"],
    ]);
    expect(hrefs("Turn on Auto-follow, then Auto Post.")).toEqual([
      ["Auto-follow", "/growth/auto-follow"],
      ["Auto Post", "/growth/auto-post"],
    ]);
    expect(hrefs("Growth — Smart Messages, Smart lists.").map(([, h]) => h))
      .toEqual(["/growth/smart-messages", "/growth/smart-lists"]);
    expect(hrefs("Smart Messages has a Mass Messages tab.")).toEqual([
      ["Smart Messages", "/growth/smart-messages?tab=mass"],
      ["Mass Messages", "/growth/smart-messages?tab=mass"],
    ]);
  });

  it("matches a label that carries brackets", () => {
    expect(only("Open Settings → Security (personal) to change it.")).toEqual({
      href: "/settings/security-personal",
      text: "Settings → Security (personal)",
    });
    expect(only("Settings → Security (organization), owners only")).toEqual({
      href: "/settings/security-org",
      text: "Settings → Security (organization)",
    });
  });

  it("never starts a new path on the word after an arrow", () => {
    expect(only("Growth → Smart lists → Settings")).toEqual({
      href: "/growth/smart-lists#go=Settings",
      text: "Growth → Smart lists",
    });
  });

  it("never links the head word inside a longer page name", () => {
    expect(findPaths("the owner's, Role Settings and Sales Settings included", ALL).map((h) => h.href))
      .toEqual(["/settings/roles", "/settings/sales"]);
    expect(findPaths("Scripts and Billing are words; manage creators and auto post too", ALL)).toEqual([]);
    expect(only("open Settings for it")?.href).toBe("/settings");
  });

  it("keeps a closing bracket out of a path written inside brackets", () => {
    expect(only("(the same timers, My Automations → Auto Mass) to send it")).toEqual({
      href: "/growth/auto-mass",
      text: "My Automations → Auto Mass",
    });
  });

  it("links the AI chat lanes under My AI Chatter, no longer under My Automations", () => {
    expect(only("switch off My AI Chatter → Auto-reply first")).toEqual({
      href: "/growth/auto-reply",
      text: "My AI Chatter → Auto-reply",
    });
    expect(only("My Automations → Auto-reply")).toBeNull();
  });

  it("stops at the label when the sentence runs on past it", () => {
    expect(only("Go to My Automations → Auto Post and press New auto post")).toEqual({
      href: "/growth/auto-post",
      text: "My Automations → Auto Post",
    });
  });

  it("falls back to the deepest page it named when the last segment is unknown", () => {
    expect(only("Analytics → Message dashboard → Something We Never Shipped")).toEqual({
      href: "/analytics/message-dashboard#go=Something+We+Never+Shipped",
      text: "Analytics → Message dashboard",
    });
  });

  it("links nothing for a group with no page under it", () => {
    expect(findPaths("Growth → Something We Never Shipped", ALL)).toEqual([]);
    expect(findPaths("Open Growth for that.", ALL)).toEqual([]);
  });

  it.each([...BARE])("links a bare mention of %s", (label) => {
    expect(only(`Ask an owner to open ${label} for you.`)?.text).toBe(label);
  });

  it("links a bare mention of an unambiguous section", () => {
    expect(only("Ask an owner to open Messages Pro for you.")).toEqual({
      href: "/messages-pro",
      text: "Messages Pro",
    });
    expect(only("A fan on the Customs queue is withheld from selling.")).toEqual({
      href: "/analytics/message-dashboard?tab=customs",
      text: "Customs",
    });
  });

  it("resolves the groups below the sidebar's divider", () => {
    expect(only("Creators → Manage creators shows the badge.")?.href).toBe("/creators");
    expect(only("Creators → Manage creators → Add creator.")?.href).toBe("/creators#go=Add+creator");
    expect(only("Employees → Manage employees → + Add employee")?.href).toBe("/employees#go=%2B+Add+employee");
  });

  it("leaves ordinary prose alone", () => {
    expect(findPaths("the growth of an account", ALL)).toEqual([]);
    expect(findPaths("Analytics update hourly.", ALL)).toEqual([]);
    expect(findPaths("Creators keep their own login.", ALL)).toEqual([]);
  });

  it("finds several paths in one answer without overlapping", () => {
    const text = "Use Growth → Profile promotion for that, or Growth → Smart Messages for a one-off.";
    const hits = findPaths(text, ALL);
    expect(hits.map((h) => h.href)).toEqual(["/growth/profile-promotion", "/growth/smart-messages"]);
    expect(hits[0].end).toBeLessThanOrEqual(hits[1].start);
  });

  it("does not trail a bold marker into the link", () => {
    expect(only("go to **Growth → Profile promotion**. There, set a Name")).toEqual({
      href: "/growth/profile-promotion",
      text: "Growth → Profile promotion",
    });
  });

  it("never returns a range outside the string", () => {
    const text = "Growth → Auto-follow";
    for (const h of findPaths(text, ALL)) {
      expect(h.start).toBeGreaterThanOrEqual(0);
      expect(h.end).toBeLessThanOrEqual(text.length);
      expect(h.end).toBeGreaterThan(h.start);
    }
  });
});


describe("every path the help manual writes names a real page", () => {
  const manual = readFileSync(resolve(__dirname, "..", "..", "..", "service", "assistant_manual.md"), "utf-8")
    .replace(/(?<!\n)\n(?!\n)/g, " ")
    .replace(/\*\*/g, "");
  const heads = [...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n) => (isDivider(n) ? [] : [n.label]));
  const SEG = `[^\\n→,;:."\`*]+`;
  const esc = (l: string) => l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const PATH = new RegExp(`\\b(?:${heads.map(esc).join("|")})\\s*→\\s*${SEG}(?:\\s*→\\s*${SEG})*`, "g");
  const paths = [...new Set([...manual.matchAll(PATH)].map((m) => m[0].trim()))];
  const LABELS = [
    ...[...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n) => (isGroup(n) ? n.children.map((c) => c.label) : [])),
    ...SETTINGS_TABS.map((t) => t.label),
    ...MESSAGE_DASHBOARD_TABS.map((t) => t.label),
    ...SMART_MESSAGES_TABS.map((t) => t.label),
  ];
  const STEPS = new Set(["New Message"]);

  const hrefOf = (parts: string[]) => findPaths(parts.join(" → "), ALL)[0]?.href.split("#")[0];

  it("finds paths to check", () => {
    expect(paths.length).toBeGreaterThan(40);
  });

  it.each(paths)("%s", (path) => {
    const parts = path.split(/\s*→\s*/).map((p) => p.trim());
    const hit = findPaths(path, ALL)[0];
    expect(hit && path.slice(hit.start, hit.end).includes("→"), `"${path}" names no page`).toBe(true);
    for (let i = 1; i < parts.length; i++) {
      const above = hrefOf(parts.slice(0, i));
      if (hrefOf(parts.slice(0, i + 1)) !== above) continue;
      const hasBelow = LABELS.some((l) => hrefOf([...parts.slice(0, i), l]) !== above);
      expect(!hasBelow || STEPS.has(parts[i]), `"${path}": "${parts[i]}" names no page or tab`).toBe(true);
      break;
    }
  });
});

describe("findPaths with the role's pages", () => {
  const TEXT = "Set it in Settings → AI keys, or ask in Help center. Customs sit in Message dashboard → Customs owed.";
  it("drops a page the role can't open, keeps the rest (a tab rides its page)", () => {
    const pages = new Set(["/help-center", "/analytics/message-dashboard"]);
    expect(findPaths(TEXT, ALL).map((h) => h.href)).toContain("/settings/ai-keys");
    expect(findPaths(TEXT, pages).map((h) => h.href)).toEqual(
      findPaths(TEXT, ALL).map((h) => h.href).filter((h) => !h.startsWith("/settings")));
    expect(findPaths(TEXT, pages).some((h) => h.href === "/analytics/message-dashboard?tab=customs")).toBe(true);
  });
  it("no pages: nothing links", () => expect(findPaths(TEXT, new Set())).toEqual([]));
  it("leaving pages out does not typecheck", () => {
    const typeOnly = () => {
      // @ts-expect-error pages is required
      findPaths(TEXT);
    };
    expect(typeof typeOnly).toBe("function");
  });
});

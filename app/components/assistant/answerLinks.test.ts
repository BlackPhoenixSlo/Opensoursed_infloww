/**
 * answerLinks — click paths resolve, and prose does not.
 *
 * Two jobs here. The first is the resolver itself: the shapes the bot
 * actually writes ("Growth → Auto-follow", a three-segment path, a label with
 * the sentence running on past it) have to land on the right route with the
 * right slice of text underlined.
 *
 * The second reads the help manual itself: every path it writes must name a
 * real page one arrow down, and every step it walks through must be a page or
 * tab the resolver knows, so a renamed page fails here, not in an answer.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER } from "@/lib/nav";
import { MESSAGE_DASHBOARD_TABS, SMART_MESSAGES_TABS } from "@/lib/pageTabs";

import { BARE, findPaths } from "./answerLinks";

/** The single hit in `text`, or null. Fails loudly on more than one. */
function only(text: string) {
  const hits = findPaths(text);
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
      href: "/growth/smart-messages?tab=mass",
      text: "Growth → Smart Messages → Mass Messages → OF mass messages",
    });
    expect(only("Messages Pro → + → Mass message")).toEqual({
      href: "/messages-pro",
      text: "Messages Pro → +",
    });
  });

  it("resolves a Settings page", () => {
    expect(only("Set it in Settings → AI keys (owner only).")).toEqual({
      href: "/settings/ai-keys",
      text: "Settings → AI keys",
    });
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
    // "Settings" is a head of its own (Your Account and the rest); as the
    // segment of a path the walk could not finish, it must not relink there.
    expect(only("Growth → Smart lists → Settings")).toEqual({
      href: "/growth/smart-lists",
      text: "Growth → Smart lists",
    });
  });

  it("never links the head word inside a longer page name", () => {
    // "Settings" stands alone as a link, but "Role Settings" is its own page.
    expect(findPaths("the owner's, Role Settings and Sales Settings included")).toEqual([]);
    expect(only("open Settings for it")?.href).toBe("/settings");
  });

  it("keeps a closing bracket out of a path written inside brackets", () => {
    expect(only("(the same timers, My Automations → Auto Mass) to send it")).toEqual({
      href: "/growth/auto-mass",
      text: "My Automations → Auto Mass",
    });
  });

  it("stops at the label when the sentence runs on past it", () => {
    // The failure this prevents: underlining "Auto Post and press New auto
    // post" and resolving it to nothing.
    expect(only("Go to My Automations → Auto Post and press New auto post")).toEqual({
      href: "/growth/auto-post",
      text: "My Automations → Auto Post",
    });
  });

  it("falls back to the deepest page it named when the last segment is unknown", () => {
    expect(only("Analytics → Message dashboard → Something We Never Shipped")).toEqual({
      href: "/analytics/message-dashboard",
      text: "Analytics → Message dashboard",
    });
  });

  it("links nothing for a group with no page under it", () => {
    // A group is a sidebar heading; its first page is a sibling, not a parent.
    expect(findPaths("Growth → Something We Never Shipped")).toEqual([]);
    expect(findPaths("Open Growth for that.")).toEqual([]);
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
    // The connect-an-account path the help bot gives a user with no account
    // (assistant_api's no-account rule): the button's name stays prose.
    expect(only("Creators → Manage creators → Add creator.")?.href).toBe("/creators");
    expect(only("Employees → Manage employees → + Add employee")?.href).toBe("/employees");
  });

  it("leaves ordinary prose alone", () => {
    // "growth" lowercase is a word; "Analytics"/"Creators" are words that
    // happen to match a nav item, so they only link as the head of a path.
    expect(findPaths("the growth of an account")).toEqual([]);
    expect(findPaths("Analytics update hourly.")).toEqual([]);
    expect(findPaths("Creators keep their own login.")).toEqual([]);
  });

  it("finds several paths in one answer without overlapping", () => {
    const text = "Use Growth → Profile promotion for that, or Growth → Smart Messages for a one-off.";
    const hits = findPaths(text);
    expect(hits.map((h) => h.href)).toEqual(["/growth/profile-promotion", "/growth/smart-messages"]);
    expect(hits[0].end).toBeLessThanOrEqual(hits[1].start);
  });

  it("does not trail a bold marker into the link", () => {
    // AnswerText strips `**` before calling this, but the function is exported
    // and has to be right on its own — a hit ending in "promotion**" would
    // underline the asterisks the whole change exists to remove.
    expect(only("go to **Growth → Profile promotion**. There, set a Name")).toEqual({
      href: "/growth/profile-promotion",
      text: "Growth → Profile promotion",
    });
  });

  it("never returns a range outside the string", () => {
    const text = "Growth → Auto-follow";
    for (const h of findPaths(text)) {
      expect(h.start).toBeGreaterThanOrEqual(0);
      expect(h.end).toBeLessThanOrEqual(text.length);
      expect(h.end).toBeGreaterThan(h.start);
    }
  });
});

// ── The manual's own paths ──────────────────────────────────────────

describe("every path the help manual writes names a real page", () => {
  // Joined back into paragraphs, since a path the source wraps is one path in
  // an answer, and with the bold markers gone, as AnswerText resolves it.
  const manual = readFileSync(resolve(__dirname, "..", "..", "..", "service", "assistant_manual.md"), "utf-8")
    .replace(/(?<!\n)\n(?!\n)/g, " ")
    .replace(/\*\*/g, "");
  const heads = [...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n) => (isDivider(n) ? [] : [n.label]));
  const SEG = `[^\\n→,;:."\`*]+`;
  const esc = (l: string) => l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const PATH = new RegExp(`\\b(?:${heads.map(esc).join("|")})\\s*→\\s*${SEG}(?:\\s*→\\s*${SEG})*`, "g");
  const paths = [...new Set([...manual.matchAll(PATH)].map((m) => m[0].trim()))];
  // Every label one arrow below anything, to probe whether a place HAS
  // pages or tabs below it.
  const LABELS = [
    ...[...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n) => (isGroup(n) ? n.children.map((c) => c.label) : [])),
    ...SETTINGS_TABS.map((t) => t.label),
    ...MESSAGE_DASHBOARD_TABS.map((t) => t.label),
    ...SMART_MESSAGES_TABS.map((t) => t.label),
  ];
  // A button a path walks through, not a page or a tab.
  const STEPS = new Set(["New Message"]);

  const hrefOf = (parts: string[]) => findPaths(parts.join(" → "))[0]?.href;

  it("finds paths to check", () => {
    expect(paths.length).toBeGreaterThan(40);
  });

  it.each(paths)("%s", (path) => {
    const parts = path.split(/\s*→\s*/).map((p) => p.trim());
    const hit = findPaths(path)[0];
    // Resolving the first segment is what carries the link past "Head → ".
    expect(hit && path.slice(hit.start, hit.end).includes("→"), `"${path}" names no page`).toBe(true);
    // Below a place with pages or tabs, a segment must name one of them. The
    // walk is checked up to the first segment that names nothing: past it the
    // path is inside a page (a row, a card, a switch), not the nav.
    for (let i = 1; i < parts.length; i++) {
      const above = hrefOf(parts.slice(0, i));
      if (hrefOf(parts.slice(0, i + 1)) !== above) continue;
      const hasBelow = LABELS.some((l) => hrefOf([...parts.slice(0, i), l]) !== above);
      expect(!hasBelow || STEPS.has(parts[i]), `"${path}": "${parts[i]}" names no page or tab`).toBe(true);
      break;
    }
  });
});

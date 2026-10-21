/**
 * answerLinks — click paths resolve, and prose does not.
 *
 * Three jobs here. The first is the resolver itself: the shapes the bot
 * actually writes ("Growth → Auto-follow", a three-segment path, a label with
 * the sentence running on past it) have to land on the right route with the
 * right slice of text underlined.
 *
 * The second is the DRIFT GUARD: answerLinks.ts copies three tab tables rather
 * than importing their page components into the widget's bundle, so the copies
 * can rot. These cases read the owning source files and assert every key still
 * exists — renaming a tab fails here instead of quietly sending readers to a
 * default tab.
 *
 * The third reads the help manual itself: every path it writes must name a
 * real page one arrow down, so a renamed page fails here, not in an answer.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { MESSAGES_TABS, SMART_MESSAGES_TABS, findPaths } from "./answerLinks";

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

  it("stops at the label when the sentence runs on past it", () => {
    // The failure this prevents: underlining "Auto Post and press New auto
    // post" and resolving it to nothing.
    expect(only("Go to My Automations → Auto Post and press New auto post")).toEqual({
      href: "/growth/auto-post",
      text: "My Automations → Auto Post",
    });
  });

  it("falls back to the group's first page when the last segment is unknown", () => {
    expect(only("Growth → Something We Never Shipped")?.href).toBe("/growth/smart-messages");
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

// ── Drift guard ─────────────────────────────────────────────────────

/** Every `key: "..."` inside the `array` literal (TABS by default) of `file`. */
function tabKeysIn(file: string, array = "TABS"): Set<string> {
  const src = readFileSync(resolve(__dirname, "..", "..", file), "utf-8");
  const start = src.indexOf(`const ${array}`);
  expect(start, `${file} has no ${array} array`).toBeGreaterThan(-1);
  const end = src.indexOf("];", start);
  const body = src.slice(start, end);
  const keys = new Set<string>();
  for (const m of body.matchAll(/key:\s*"([^"]+)"/g)) keys.add(m[1]);
  expect(keys.size, `${file} ${array} parsed empty`).toBeGreaterThan(0);
  return keys;
}

/** Every key of the `LOOKUP` map in `file` (the values `?tab=` may name). */
function lookupKeysIn(file: string): Set<string> {
  const src = readFileSync(resolve(__dirname, "..", "..", file), "utf-8");
  const m = /const LOOKUP[^=]*=\s*\{([^}]*)\}/.exec(src);
  expect(m, `${file} has no LOOKUP map`).not.toBeNull();
  const keys = new Set<string>();
  for (const k of m![1].matchAll(/(\w+):/g)) keys.add(k[1]);
  return keys;
}

describe("the copied tab tables still match the pages that own them", () => {
  const cases: Array<[string, () => Set<string>, Record<string, string>, string]> = [
    ["app/analytics/message-dashboard/page.tsx", () => tabKeysIn("app/analytics/message-dashboard/page.tsx"), MESSAGES_TABS, "MESSAGES_TABS"],
    ["components/growth/SmartMessagesPage.tsx", () => lookupKeysIn("components/growth/SmartMessagesPage.tsx"), SMART_MESSAGES_TABS, "SMART_MESSAGES_TABS"],
  ];

  it.each(cases)("%s", (where, keysOf, table, name) => {
    const real = keysOf();
    for (const [label, key] of Object.entries(table)) {
      expect(
        real.has(key),
        `${name}["${label}"] → "${key}" is not handled by ${where}`,
      ).toBe(true);
    }
  });
});

// ── The manual's own paths ──────────────────────────────────────────

describe("every path the help manual writes names a real page", () => {
  // Joined back into paragraphs: a path the source wraps is one path in an answer.
  const manual = readFileSync(resolve(__dirname, "..", "..", "..", "service", "assistant_manual.md"), "utf-8")
    .replace(/(?<!\n)\n(?!\n)/g, " ");
  // A head with pages below it, then its first segment up to the next arrow or
  // the end of the phrase.
  const PATH = /\b(OF Manager|Analytics|Growth|Share for Share|My Automations|Creators|Employees|Settings) → ([^\n→,;:()."*`]+)/g;
  const paths = [...new Set([...manual.matchAll(PATH)].map((m) => `${m[1]} → ${m[2].trim()}`))];

  it("finds paths to check", () => {
    expect(paths.length).toBeGreaterThan(20);
  });

  it.each(paths)("%s", (path) => {
    const hit = findPaths(path)[0];
    // Resolving the first segment is what carries the link past "Head → ".
    expect(hit && path.slice(hit.start, hit.end).includes("→"), `"${path}" names no page`).toBe(true);
  });
});

import { describe, expect, it } from "vitest";

import { canOpenChats, commandLinks, confirmation, prepass, type PrepassHit } from "./prepass";

const OWNER = commandLinks({ chatterOnly: false, grantedPages: null });
const CHATTER = commandLinks({ chatterOnly: true, grantedPages: null });

describe("prepass", () => {
  it.each<[string, PrepassHit | null]>([
    // An imperative verb + a page label navigates.
    ["open settings", { kind: "navigate", href: "/settings", label: "Settings" }],
    ["Open Settings.", { kind: "navigate", href: "/settings", label: "Settings" }],
    ["please go to the auto post page", { kind: "navigate", href: "/growth/auto-post", label: "Auto Post" }],
    ["take me to fan reports", { kind: "navigate", href: "/analytics/fan-reports", label: "Fan reports" }],
    ["show me the dashboard", { kind: "navigate", href: "/", label: "Dashboard" }],
    ["open messages pro", { kind: "navigate", href: "/messages-pro", label: "Messages Pro" }],
    ["open audit log", { kind: "navigate", href: "/settings/audit", label: "Audit log" }],
    ["switch to manage creators", { kind: "navigate", href: "/creators", label: "Manage creators" }],
    // Theme.
    ["dark mode", { kind: "theme", theme: "dark" }],
    ["switch to light mode", { kind: "theme", theme: "light" }],
    ["turn on dark mode", { kind: "theme", theme: "dark" }],
    ["toggle theme", { kind: "theme", theme: "toggle" }],
    // A fan's chat.
    ["open @Lena_99", { kind: "chat", handle: "Lena_99" }],
    ["chat with @lena", { kind: "chat", handle: "lena" }],
    ["open chat with @lena", { kind: "chat", handle: "lena" }],
    ["open @lena's chat", { kind: "chat", handle: "lena" }],
    // Questions and everything else go to the LLM unchanged.
    ["how do I open settings?", null],
    ["how do I open settings", null],
    ["where is dark mode", null],
    ["can you open settings", null],
    ["open settings?", null],
    ["settings", null],
    ["open the pod bay doors", null],
    ["show me revenue for today", null],
    ["open my automations", null], // a group, not a page
    ["message @lena saying hi", null],
    ["send a mass message to everyone", null],
    ["", null],
  ])("%j", (input, want) => {
    expect(prepass(input, OWNER)).toEqual(want);
  });

  it("only the session's visible pages: a chatter cannot open an owner page", () => {
    expect(prepass("open audit log", CHATTER)).toBeNull();
    expect(prepass("open manage creators", CHATTER)).toBeNull();
    expect(prepass("open system", OWNER)).toBeNull(); // master only
    expect(prepass("open system", commandLinks({ chatterOnly: false, grantedPages: null, master: true })))
      .toEqual({ kind: "navigate", href: "/settings/system", label: "System" });
    expect(prepass("open scripts", CHATTER)).toEqual({ kind: "navigate", href: "/growth/scripts", label: "Scripts" });
  });

  it("a fan's chat only when the session may open Messages Pro; else it goes on to the LLM", () => {
    const denied = commandLinks({ chatterOnly: true, grantedPages: new Set(["/growth/scripts"]) });
    expect(canOpenChats(CHATTER)).toBe(true);
    expect(canOpenChats(denied)).toBe(false);
    expect(prepass("open @lena", denied)).toBeNull();
    expect(prepass("chat with @lena", denied)).toBeNull();
    expect(prepass("open scripts", denied)).toEqual({ kind: "navigate", href: "/growth/scripts", label: "Scripts" });
  });

  it("confirms in a short line", () => {
    expect(confirmation({ kind: "navigate", href: "/settings", label: "Settings" })).toBe("Opened Settings.");
    expect(confirmation({ kind: "theme", theme: "toggle" }, "light")).toBe("Switched to light mode.");
    expect(confirmation({ kind: "chat", handle: "lena" })).toBe("Opened @lena's chat.");
  });
});

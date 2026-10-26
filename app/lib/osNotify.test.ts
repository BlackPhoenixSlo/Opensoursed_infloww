import { afterEach, describe, expect, it, vi } from "vitest";

import { hasShellNotify, osNotify } from "./osNotify";

const N = { id: "m1", title: "Ann", body: "hi", href: "/messages-pro/a/1" };

afterEach(() => {
  delete window.fasttShell;
  vi.unstubAllGlobals();
});

describe("osNotify in the desktop app", () => {
  it("hands the payload to fasttShell.notify and ignores the web permission", async () => {
    const notify = vi.fn().mockResolvedValue(true);
    const web = vi.fn();
    vi.stubGlobal("Notification", Object.assign(web, { permission: "denied" }));
    window.fasttShell = { isDesktop: true, notify };

    expect(hasShellNotify()).toBe(true);
    await expect(osNotify(N)).resolves.toBe(true);
    expect(notify).toHaveBeenCalledWith(N);
    expect(web).not.toHaveBeenCalled();
  });

  it("sends an empty href when there is none, and reports a refusal or a throw as false", async () => {
    const notify = vi.fn().mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("ipc"));
    window.fasttShell = { isDesktop: true, notify };
    vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(osNotify({ id: "r", title: "Timed reminder", body: "Time's up" })).resolves.toBe(false);
    expect(notify).toHaveBeenCalledWith({ id: "r", title: "Timed reminder", body: "Time's up", href: "" });
    await expect(osNotify(N)).resolves.toBe(false);
  });
});

describe("osNotify in a browser", () => {
  it("uses the web Notification with the id as tag when permission is granted", async () => {
    const shown: unknown[][] = [];
    vi.stubGlobal("Notification", Object.assign(
      function Notification(...args: unknown[]) { shown.push(args); },
      { permission: "granted" },
    ));
    expect(hasShellNotify()).toBe(false);
    await expect(osNotify(N)).resolves.toBe(true);
    expect(shown).toEqual([["Ann", { body: "hi", tag: "m1" }]]);
  });

  it("a click focuses the app and opens the Fan like any notification click", async () => {
    const made: { onclick: (() => void) | null; close: () => void }[] = [];
    vi.stubGlobal("Notification", Object.assign(
      function Notification(this: (typeof made)[number]) { this.onclick = null; this.close = vi.fn(); made.push(this); },
      { permission: "granted" },
    ));
    const focus = vi.spyOn(window, "focus").mockImplementation(() => {});
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    try {
      await osNotify({ ...N, href: "/messages-pro/a/1?fanTab=Ann" });
      made[0].onclick!();
      expect(focus).toHaveBeenCalled();
      expect(open).toHaveBeenCalledWith("", "messages-pro", expect.any(String));
      expect(made[0].close).toHaveBeenCalled();
    } finally {
      focus.mockRestore();
      open.mockRestore();
    }
  });

  it("does nothing, and never asks, without permission", async () => {
    const requestPermission = vi.fn();
    const web = vi.fn();
    vi.stubGlobal("Notification", Object.assign(web, { permission: "default", requestPermission }));
    await expect(osNotify(N)).resolves.toBe(false);
    expect(web).not.toHaveBeenCalled();
    expect(requestPermission).not.toHaveBeenCalled();
  });
});

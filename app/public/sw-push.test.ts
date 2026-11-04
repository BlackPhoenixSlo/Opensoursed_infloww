// @vitest-environment node
/**
 * public/sw-push.js, run as the browser runs it: evaluated in a `vm` context
 * whose `self` is a fake service worker global (registration.showNotification,
 * clients, navigator). Covers the push display rule (always shows, but off
 * Apple a focused visible window that acks toasts it instead; no ack within
 * ACK_MS, a nack or a failed post and it shows), a bad payload, the click,
 * sw-images.js surviving a broken push file (and still showing every push),
 * and sw-images.js's `// push sha256:` line equal to sw-push.js's hash (the bump).
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const PUSH_SRC = readFileSync(join(__dirname, "sw-push.js"), "utf8");
const IMAGES_SRC = readFileSync(join(__dirname, "sw-images.js"), "utf8");

const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
const MAC_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const MAC_SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";

interface FakeClient { focused: boolean; visibilityState: string; focus: ReturnType<typeof vi.fn>; postMessage: ReturnType<typeof vi.fn> }
/** `answer`: what the page replies to a push-notice on its port (undefined: no listener, no reply). */
const client = (focused: boolean, visibilityState = focused ? "visible" : "hidden", answer?: boolean): FakeClient => ({
  focused, visibilityState, focus: vi.fn(async () => undefined),
  postMessage: vi.fn((_msg: unknown, ports?: MessagePort[]) => {
    if (answer !== undefined) ports?.[0]?.postMessage(answer);
  }),
});

type Handler = (event: unknown) => void;

function load({ ua = CHROME, clients = [] as FakeClient[], manifest = { name: "Example App" } as unknown } = {}) {
  const handlers: Record<string, Handler> = {};
  const self = {
    navigator: { userAgent: ua },
    addEventListener: (type: string, fn: Handler) => { handlers[type] = fn; },
    registration: { showNotification: vi.fn(async () => undefined) },
    clients: { matchAll: vi.fn(async () => clients), openWindow: vi.fn(async () => null) },
    __swPush: undefined as unknown,
  };
  const fetch = vi.fn(async () => {
    if (manifest instanceof Error) throw manifest;
    return { json: async () => manifest };
  });
  vm.runInContext(PUSH_SRC, vm.createContext({ self, fetch, AbortController, MessageChannel, setTimeout, clearTimeout, console }));
  return { self, handlers, fetch };
}

async function push(handlers: Record<string, Handler>, data: unknown) {
  let done: Promise<unknown> = Promise.resolve();
  handlers.push({
    data: data === null ? null : { json: () => { if (data instanceof Error) throw data; return data; } },
    waitUntil: (p: Promise<unknown>) => { done = p; },
  });
  await done;
}

async function click(handlers: Record<string, Handler>, data: unknown) {
  let done: Promise<unknown> = Promise.resolve();
  const notification = { data, close: vi.fn() };
  handlers.notificationclick({ notification, waitUntil: (p: Promise<unknown>) => { done = p; } });
  await done;
  return notification;
}

const payload = {
  v: 1, tag: "100:m5004", title: "Tipper", body: "Tipped you $5", type: "tip", account_id: "100",
  href: "/messages-pro/100/779?refresh=media&fanTab=Tipper", icon: "/icon.svg",
};
const shown = {
  body: "Tipped you $5", tag: "100:m5004", icon: "/icon.svg",
  data: { href: "/messages-pro/100/779?refresh=media&fanTab=Tipper" },
};

describe("sw-push.js: push", () => {
  it("no window: shows it, tag, link and icon from the payload", async () => {
    const { self, handlers } = load();
    await push(handlers, payload);
    expect(self.registration.showNotification.mock.calls).toEqual([["Tipper", shown]]);
  });

  it("a bad payload still shows: the manifest's name and \"New activity\"", async () => {
    const { self, handlers } = load();
    await push(handlers, new SyntaxError("not json"));
    await push(handlers, null);
    expect(self.registration.showNotification.mock.calls).toEqual([
      ["Example App", { body: "New activity", data: { href: "/" } }],
      ["Example App", { body: "New activity", data: { href: "/" } }],
    ]);
  });

  it("no manifest either: the default brand", async () => {
    const { self, handlers } = load({ manifest: new Error("offline") });
    await push(handlers, "junk");
    expect(self.registration.showNotification.mock.calls).toEqual([["Inflowwww", { body: "New activity", data: { href: "/" } }]]);
  });

  it("off Apple, a focused visible window that acks toasts it instead: no OS notification", async () => {
    const page = client(true, "visible", true);
    const other = client(false);
    const { self, handlers } = load({ ua: MAC_CHROME, clients: [other, page] });
    await push(handlers, payload);
    expect(self.registration.showNotification).not.toHaveBeenCalled();
    expect(page.postMessage.mock.calls.map((c) => c[0])).toEqual([{ type: "push-notice", payload }]);
    expect(other.postMessage).not.toHaveBeenCalled();
  });

  describe("the hand-off falls back to the OS notification", () => {
    beforeEach(() => { vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }); });
    afterEach(() => { vi.useRealTimers(); });

    it("no listener yet (a focused popout still booting): no ack, shown once ACK_MS (1.5 s) passed", async () => {
      const page = client(true);
      const { self, handlers } = load({ clients: [page] });
      expect((self.__swPush as { ACK_MS: number }).ACK_MS).toBe(1500);
      const done = push(handlers, payload);
      await vi.advanceTimersByTimeAsync(1499);
      expect(page.postMessage).toHaveBeenCalledTimes(1);
      expect(self.registration.showNotification).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      await done;
      expect(self.registration.showNotification.mock.calls).toEqual([["Tipper", shown]]);
    });

    it.each([
      ["the page nacks (a Creator out of its scope)", client(true, "visible", false)],
      ["the post fails", Object.assign(client(true), { postMessage: vi.fn(() => { throw new Error("detached"); }) })],
    ])("%s: shown at once, no timer run", async (_l, page) => {
      const { self, handlers } = load({ clients: [page] });
      await push(handlers, payload); // fake timers never advanced: resolves without ACK_MS
      expect(page.postMessage).toHaveBeenCalledTimes(1);
      expect(self.registration.showNotification.mock.calls).toEqual([["Tipper", shown]]);
    });
  });

  it.each([
    // [label, ua, clients]
    ["iPhone, even with a focused window", IPHONE, [client(true)]],
    ["Safari on a Mac / iPadOS, even with a focused window", MAC_SAFARI, [client(true)]],
    ["Chrome, windows open but none focused and visible", CHROME, [client(false, "visible"), client(true, "hidden")]],
  ])("shows it: %s", async (_l, ua, clients) => {
    const { self, handlers } = load({ ua, clients });
    await push(handlers, payload);
    expect(self.registration.showNotification.mock.calls).toEqual([["Tipper", shown]]);
    for (const c of clients) expect(c.postMessage).not.toHaveBeenCalled();
  });

  it("the relay's test notice (no Creator) shows even over a focused window", async () => {
    const page = client(true);
    const { self, handlers } = load({ clients: [page] });
    await push(handlers, { v: 1, tag: "test:1", title: "Example App test", body: "Push works with the app closed." });
    expect(self.registration.showNotification).toHaveBeenCalledTimes(1);
    expect(page.postMessage).not.toHaveBeenCalled();
  });

  it("exposes its pure parts", () => {
    const { self } = load();
    const sw = self.__swPush as { payloadToOptions: (p: unknown, b: string | null) => unknown; pickClient: (l: unknown[]) => unknown };
    expect(sw.payloadToOptions({ title: "T", href: "//evil.example" }, null)).toEqual({ title: "T", options: { body: "New activity", data: { href: "/" } } });
    expect(sw.pickClient([])).toBeNull();
  });
});

describe("sw-push.js: notificationclick", () => {
  it("closes it, focuses the focused window and tells it the link", async () => {
    const first = client(false);
    const focused = client(true);
    const { self, handlers } = load({ clients: [first, focused] });
    const n = await click(handlers, { href: "/messages-pro/100/779?fanTab=Tipper" });
    expect(n.close).toHaveBeenCalled();
    expect(focused.focus).toHaveBeenCalled();
    expect(focused.postMessage.mock.calls).toEqual([[{ type: "open-notification", href: "/messages-pro/100/779?fanTab=Tipper" }]]);
    expect(first.postMessage).not.toHaveBeenCalled();
    expect(self.clients.openWindow).not.toHaveBeenCalled();
  });

  it("a visible window before a hidden first one; a focus refused still gets the link", async () => {
    const hidden = client(false);
    const visible = client(false, "visible");
    visible.focus.mockRejectedValue(new Error("not allowed"));
    const { handlers } = load({ clients: [hidden, visible] });
    await click(handlers, { href: "/x" });
    expect(visible.postMessage.mock.calls).toEqual([[{ type: "open-notification", href: "/x" }]]);
  });

  it("no window: opens the link in a new one (an off-site link becomes /)", async () => {
    const { self, handlers } = load();
    await click(handlers, { href: "/messages-pro/100/779?fanTab=Tipper" });
    await click(handlers, { href: "https://evil.example/" });
    expect(self.clients.openWindow.mock.calls).toEqual([["/messages-pro/100/779?fanTab=Tipper"], ["/"]]);
  });
});

describe("sw-images.js", () => {
  const lines = IMAGES_SRC.split("\n");

  it("keeps eslint off on line 1 and imports sw-push.js at the top", () => {
    expect(lines[0]).toBe("/* eslint-disable */");
    expect(lines[2]).toMatch(/^try \{ importScripts\("\/sw-push\.js"\); \} catch \(e\) \{$/);
  });

  it("line 2 is `// push sha256:<sw-push.js's sha256>`: a sw-push.js change must update it, which changes sw-images.js (the bump)", () => {
    const hash = createHash("sha256").update(readFileSync(join(__dirname, "sw-push.js"))).digest("hex");
    expect(lines[1]).toBe(`// push sha256:${hash}`);
  });

  it("a broken sw-push.js never stops the image cache worker from installing", () => {
    const types: string[] = [];
    const self = { addEventListener: (t: string) => { types.push(t); } };
    const importScripts = vi.fn(() => { throw new SyntaxError("bad push file"); });
    const warn = vi.fn();
    vm.runInContext(IMAGES_SRC, vm.createContext({ self, importScripts, console: { warn } }));
    expect(importScripts).toHaveBeenCalledWith("/sw-push.js");
    expect(warn).toHaveBeenCalled();
    expect(types).toEqual(expect.arrayContaining(["install", "activate", "fetch"]));
  });

  it("a broken sw-push.js still shows on push (the manifest's name, \"New activity\") and a click opens the app", async () => {
    const handlers: Record<string, Handler> = {};
    const self = {
      addEventListener: (t: string, fn: Handler) => { handlers[t] = fn; },
      registration: { showNotification: vi.fn(async () => undefined) },
      clients: { openWindow: vi.fn(async () => null) },
    };
    let manifest: unknown = { name: "Example App" };
    const fetch = vi.fn(async () => {
      if (manifest instanceof Error) throw manifest;
      return { json: async () => manifest };
    });
    const importScripts = vi.fn(() => { throw new SyntaxError("bad push file"); });
    vm.runInContext(IMAGES_SRC, vm.createContext({ self, importScripts, fetch, console: { warn: vi.fn() } }));
    await push(handlers, payload);
    manifest = new Error("offline");
    await push(handlers, null);
    expect(self.registration.showNotification.mock.calls).toEqual([
      ["Example App", { body: "New activity", data: { href: "/" } }],
      ["Inflowwww", { body: "New activity", data: { href: "/" } }],
    ]);
    const n = await click(handlers, { href: "/x" });
    expect(n.close).toHaveBeenCalled();
    expect(self.clients.openWindow.mock.calls).toEqual([["/"]]);
  });
});

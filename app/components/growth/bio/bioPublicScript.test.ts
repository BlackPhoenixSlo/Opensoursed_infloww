/**
 * The public bio page's own script (service/bio_pages/public/script.js) in jsdom: its served index.html body, one
 * Profile JSON and Reveal answer from a stubbed fetch, a user agent per row. Pins what the editor promises: a Link with
 * the 18+ Age Gate never Reveals from a `?link=` shortcut until Continue (asked once: the in-app Continue hands the
 * shortcut out with `age=ok`), and a Reveal answer is navigated to only as an http(s) address, else error + Retry.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const PUBLIC = resolve(__dirname, "..", "..", "..", "..", "service", "bio_pages", "public");
const SCRIPT = readFileSync(resolve(PUBLIC, "script.js"), "utf-8");
const BODY = readFileSync(resolve(PUBLIC, "index.html"), "utf-8")
  .match(/<body[^>]*>([\s\S]*)<\/body>/)![1]
  .replace(/<script[\s\S]*?<\/script>/g, "");

const DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36";
const ANDROID_IG = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130 Mobile Instagram 300.0";

type Link = { id: string; title: string; isAdult: boolean; mode: string; tracking: boolean; botCheck: boolean };
const link = (id: string, isAdult: boolean, mode = "direct"): Link =>
  ({ id, title: id, isAdult, mode, tracking: false, botCheck: false });
const LINKS = [link("adult0000001", true), link("plain0000001", false),
  link("adultesc0001", true, "escape_ig"), link("plainesc0001", false, "escape_ig")];

type VirtualConsole = { on(ev: string, fn: (e: Error) => void): void; off(ev: string, fn: (e: Error) => void): void };
const virtualConsole = () => (globalThis as unknown as { jsdom: { virtualConsole: VirtualConsole } }).jsdom.virtualConsole;
let onJsdomError: ((e: Error) => void) | null = null;

/** Load the page at /alice?link=<shortcut> (more query may follow) under `ua`; Reveal answers `realUrl`. Resolves once
 * the Profile renders. */
async function load(ua: string, shortcut: string | null, realUrl = "https://dest.test/x") {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
  window.history.replaceState({}, "", shortcut ? `/alice?link=${shortcut}` : "/alice");
  document.body.innerHTML = BODY
    + '<script type="application/json" id="profile-bootstrap">{"username":"alice","profilePath":"/alice","trackingCode":null}</script>';
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.startsWith("/api/profiles/")
      ? { profile: { id: "p1", displayName: "Alice", bio: "", avatarUrl: "", mode: "direct", verified: false }, links: LINKS }
      : url.startsWith("/.netlify/functions/reveal") ? { realUrl } : {};
    return { ok: true, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  // jsdom reports each navigation to another document as "Not implemented: navigation" on its virtual console
  const navErrors: string[] = [];
  onJsdomError = (e: Error) => { if (/navigation/i.test(e.message)) navErrors.push(e.message); };
  virtualConsole().on("jsdomError", onJsdomError);
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
  // The script's DOMContentLoaded handler, run once here (never left on document for the next row)
  const onDocument = vi.spyOn(document, "addEventListener").mockImplementation(() => {});
  new Function(SCRIPT)();
  const ready = onDocument.mock.calls.find(([type]) => type === "DOMContentLoaded")![1] as () => void;
  onDocument.mockRestore();
  ready();
  await vi.waitFor(() => expect(document.querySelectorAll(".link-card").length).toBe(LINKS.length));
  const reveals = () => fetchMock.mock.calls.filter(([u]) => String(u).includes("/reveal")).length;
  const settle = () => new Promise(r => setTimeout(r, 30));
  return { reveals, navErrors, settle };
}

const gateOpen = () => !document.getElementById("overlay")!.classList.contains("hidden");
const shown = (id: string) => !document.getElementById(id)!.classList.contains("hidden");

afterEach(() => {
  if (onJsdomError) virtualConsole().off("jsdomError", onJsdomError);
  onJsdomError = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Link Shortcut and the 18+ Age Gate", () => {
  it.each([
    ["desktop, adult direct", DESKTOP, "adult0000001", true],
    ["desktop, adult escape", DESKTOP, "adultesc0001", true],
    ["Android in-app, adult escape", ANDROID_IG, "adultesc0001", true],
    ["desktop, plain direct", DESKTOP, "plain0000001", false],
    ["Android in-app, plain escape", ANDROID_IG, "plainesc0001", false],
  ])("%s", async (_name, ua, shortcut, gated) => {
    const page = await load(ua, shortcut);
    await page.settle();
    expect(gateOpen()).toBe(gated);
    expect(page.reveals()).toBe(gated ? 0 : 1);
  });

  it("desktop adult shortcut: Continue Reveals and navigates", async () => {
    const page = await load(DESKTOP, "adult0000001");
    await page.settle();
    expect(page.reveals()).toBe(0);
    document.getElementById("continueBtn")!.click();
    await vi.waitFor(() => expect(page.reveals()).toBe(1));
    await vi.waitFor(() => expect(page.navErrors.length).toBe(1));
  });

  it("Android in-app adult escape shortcut: Continue hands the shortcut out marked age=ok, no Reveal in-app", async () => {
    const page = await load(ANDROID_IG, "adultesc0001");
    await page.settle();
    expect(gateOpen()).toBe(true);
    document.getElementById("continueBtn")!.click();
    await page.settle();
    expect(window.location.pathname + window.location.search).toBe("/alice?link=adultesc0001&age=ok");
    expect(page.reveals()).toBe(0);
  });

  it.each([
    ["handed-out shortcut (age=ok): no second gate, Reveals, flag dropped", "adultesc0001&age=ok", false, 1],
    ["age=ok for a direct adult shortcut too", "adult0000001&age=ok", false, 1],
    ["any other age value still gates", "adultesc0001&age=1", true, 0],
  ])("desktop: %s", async (_name, shortcut, gated, reveals) => {
    const page = await load(DESKTOP, shortcut);
    await page.settle();
    expect(gateOpen()).toBe(gated);
    expect(page.reveals()).toBe(reveals);
    expect(window.location.search).not.toContain("age=");
  });

  it("age=ok covers only that load's shortcut: a tap on another adult card still gates", async () => {
    const page = await load(DESKTOP, "adultesc0001&age=ok");
    await vi.waitFor(() => expect(page.reveals()).toBe(1));
    (document.querySelectorAll(".link-card")[0] as HTMLElement).click();  // adult0000001
    await page.settle();
    expect(gateOpen()).toBe(true);
    expect(page.reveals()).toBe(1);
  });
});

describe("Reveal answers navigated to", () => {
  it.each([
    ["https://dest.test/x", 1],
    ["/local/path", 1],
    ["javascript:window.__pwned=1", 0],  // jsdom never runs it; the __pwned check below stays as the guard
    ["data:text/html,<b>x</b>", 0],
    ["vbscript:msgbox(1)", 0],
  ])("%s → %d navigation(s)", async (realUrl, navigations) => {
    const page = await load(DESKTOP, "plain0000001", realUrl);
    await vi.waitFor(() => expect(page.reveals()).toBe(1));
    await page.settle();
    expect(page.navErrors.length).toBe(navigations);
    expect(shown("revealError")).toBe(navigations === 0);  // a rejected answer shows the toast with Retry
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it.each(["javascript:window.__pwned=1", "data:text/html,<b>x</b>", ""])(
    "Age Gate Continue, answer %j: gate stays open with the error and Retry", async (realUrl) => {
      const page = await load(DESKTOP, "adult0000001", realUrl);
      await page.settle();
      const btn = document.getElementById("continueBtn")!;
      btn.click();
      await vi.waitFor(() => expect(btn.textContent).toBe("Retry"));
      await page.settle();
      expect(gateOpen()).toBe(true);
      expect(shown("overlayError")).toBe(true);
      expect(btn.getAttribute("aria-disabled")).toBeNull();
      expect(page.navErrors.length).toBe(0);
      btn.click();  // Retry Reveals again
      await vi.waitFor(() => expect(page.reveals()).toBe(2));
    });
});

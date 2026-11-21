import { describe, expect, it, vi } from "vitest";
import { bindGoLiveWindow, DOWNLOAD_APP, GO_LIVE_PAGE, OPENED, OPENED_SIGN_IN, WEB_HINT, DESKTOP_HINT } from "./ofMirrorGoLiveWindow";
import { bindWrites, NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
import { load } from "./ofMirrorData.fixtures";
import { BRAND_NAME } from "./brand";
import { RelayError } from "./relay";
import { switchOn } from "./ofMirrorNewWrites";

const start = (doc: Document) => doc.querySelector<HTMLButtonElement>(".b-streaming__btn-start")!;
const status = (doc: Document) => doc.querySelector(".b-stream-status-connect")!.textContent!.trim();
const noteText = (doc: Document) => doc.getElementById("oi-note")?.textContent ?? null;
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("Go live's Start with the desktop Go live window on (ticket 127)", () => {
  it("is Go live's own page", () => {
    expect(GO_LIVE_PAGE).toBe("streaming/index");
  });

  it("outside the desktop app: Start becomes the Download the app button, opening the download page", () => {
    const doc = load(GO_LIVE_PAGE);
    const download = vi.fn();
    bindGoLiveWindow(doc, { desktop: false, accountId: "1001", download });
    const b = start(doc);
    expect(DOWNLOAD_APP).toBe(`Download the ${BRAND_NAME} app`);
    expect([b.disabled, b.title, b.textContent!.trim(), b.hasAttribute("data-oi-wired")]).toEqual([false, "", DOWNLOAD_APP, true]);
    expect(status(doc)).toBe(WEB_HINT);
    b.click();
    expect(download).toHaveBeenCalledTimes(1);
  });

  it("inside the desktop app: Start stays Start Live Video and asks the bridge for the Creator's window, nothing else", async () => {
    const doc = load(GO_LIVE_PAGE);
    const open = vi.fn().mockResolvedValue({ ok: true });
    const download = vi.fn();
    bindGoLiveWindow(doc, { desktop: true, accountId: "1001", open, download });
    const b = start(doc);
    expect([b.disabled, b.title, b.textContent!.trim()]).toEqual([false, "", "Start Live Video"]);
    expect(status(doc)).toBe(DESKTOP_HINT);
    b.click();
    await flush();
    expect(open).toHaveBeenCalledWith("1001");
    expect(download).not.toHaveBeenCalled();
    expect(noteText(doc)).toBe(OPENED);
  });

  it("no Relay session: the desktop opened OF's login page, so the note says to sign in there", async () => {
    const doc = load(GO_LIVE_PAGE);
    const open = vi.fn().mockResolvedValue({ ok: true, signIn: true });
    bindGoLiveWindow(doc, { desktop: true, accountId: "1001", open, download: vi.fn() });
    start(doc).click();
    await flush();
    expect(noteText(doc)).toBe(OPENED_SIGN_IN);
  });

  it("inside the desktop app with All Creators: asks to pick one, calls nothing", () => {
    const doc = load(GO_LIVE_PAGE);
    const open = vi.fn();
    bindGoLiveWindow(doc, { desktop: true, accountId: null, open, download: vi.fn() });
    start(doc).click();
    expect(open).not.toHaveBeenCalled();
    expect(noteText(doc)).toBe(SELECT_MODEL);
  });

  it("a refused open shows the desktop's plain message as an error; a thrown one a generic error", async () => {
    const doc = load(GO_LIVE_PAGE);
    const open = vi.fn().mockResolvedValueOnce({ ok: false, error: "You're not allowed to go live for this Creator." }).mockRejectedValueOnce(new Error("x"));
    bindGoLiveWindow(doc, { desktop: true, accountId: "1001", open, download: vi.fn() });
    start(doc).click();
    await flush();
    expect(noteText(doc)).toBe("You're not allowed to go live for this Creator.");
    expect(doc.getElementById("oi-note")!.style.color).toBe("rgb(255, 69, 69)");
    start(doc).click();
    await flush();
    expect(noteText(doc)).toMatch(/Couldn't open Go live/);
  });

  it("an old desktop app without the bridge call gets the Download button, as the web", () => {
    const doc = load(GO_LIVE_PAGE);
    bindGoLiveWindow(doc, { desktop: true, accountId: "1001", download: vi.fn() });
    expect(start(doc).textContent!.trim()).toBe(DOWNLOAD_APP);
  });

  it("the read-only click fallback leaves the wired Start alone", async () => {
    const doc = load(GO_LIVE_PAGE);
    const open = vi.fn().mockResolvedValue({ ok: true });
    bindGoLiveWindow(doc, { desktop: true, accountId: "1001", open, download: vi.fn() });
    const handlers = { uploadProfileImage: vi.fn(), saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(), navigate: vi.fn() };
    const unbind = bindWrites(doc, GO_LIVE_PAGE, handlers, true);
    start(doc).click();
    await flush();
    expect(noteText(doc)).toBe(OPENED);
    expect(handlers.submit).not.toHaveBeenCalled();
    unbind();
  });

  it("unbinding restores today's disabled Start and Not available status", () => {
    const doc = load(GO_LIVE_PAGE);
    const download = vi.fn();
    const unbind = bindGoLiveWindow(doc, { desktop: false, accountId: "1", download });
    unbind();
    const b = start(doc);
    expect([b.disabled, b.title, b.textContent!.trim(), b.hasAttribute("data-oi-wired")]).toEqual([true, NOT_YET, "Start Live Video", false]);
    expect(status(doc)).toBe(NOT_YET);
    b.click();
    expect(download).not.toHaveBeenCalled();
  });
});

describe("the switch probe (OF_LIVE_WINDOW_ENABLED)", () => {
  it("on only when the Relay answers; its 404 (switch off) or any failure is off, today's page", async () => {
    expect(await switchOn(async () => ({ enabled: true }), "enabled")).toBe(true);
    expect(await switchOn(async () => ({ enabled: false }), "enabled")).toBe(false);
    expect(await switchOn(async () => { throw new RelayError(404, "Not Found"); }, "enabled")).toBe(false);
    expect(await switchOn(async () => { throw new Error("offline"); }, "enabled")).toBe(false);
  });
});

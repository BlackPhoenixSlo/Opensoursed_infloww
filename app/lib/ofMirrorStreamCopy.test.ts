import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bindStreamCopy, FIELD_NAMES, KEY_COPIED, LINK_COPIED, LINK_NAMES, NO_KEY, NO_LINK, streamCopy, type StreamCopy } from "./ofMirrorStreamCopy";
import { NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";

const KEY = "oi-synthetic-stream-key-test";
const SERVER = "rtmp://synthetic.invalid/live";
const SETTINGS = { streamingRtmpServer: SERVER, streamingRtmpKey: KEY };
const CHAT = "https://onlyfans.com/my/streaming/chat";

describe("streamCopy", () => {
  it.each<[string, StreamCopy, unknown, string | null, boolean, ReturnType<typeof streamCopy>]>([
    ["server", "server", SETTINGS, null, true, { text: SERVER, toast: LINK_COPIED }],
    ["server in All Creators (the shown stand-in's)", "server", SETTINGS, null, false, { text: SERVER, toast: LINK_COPIED }],
    ["server before the read lands", "server", undefined, null, true, { note: NO_LINK, error: true }],
    ["key", "key", SETTINGS, null, true, { text: KEY, toast: KEY_COPIED }],
    ["key in All Creators: Select-model note", "key", SETTINGS, null, false, { note: SELECT_MODEL, error: false }],
    ["key missing", "key", { streamingRtmpServer: SERVER }, null, true, { note: NO_KEY, error: true }],
    ["key blank", "key", { streamingRtmpKey: "  " }, null, true, { note: NO_KEY, error: true }],
    ["chat link (its text, trimmed)", "chat", SETTINGS, ` ${CHAT} `, true, { text: CHAT, toast: LINK_COPIED }],
    ["widgets link in All Creators", "widgets", undefined, "https://obs-settings.onlyfans.com/", false, { text: "https://obs-settings.onlyfans.com/", toast: LINK_COPIED }],
    ["link with no text", "chat", SETTINGS, null, true, { note: NO_LINK, error: true }],
  ])("%s", (_, control, settings, link, selected, want) => {
    expect(streamCopy(control, settings, link, selected)).toEqual(want);
  });
});

describe("bindStreamCopy", () => {
  const load = () => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/streaming.html"), "utf8");
    return document;
  };
  const copyBtn = (d: Document, c: string) => d.querySelector<HTMLButtonElement>(`button[data-oi-stream-copy='${c}']`)!;
  const write = vi.fn<(t: string) => Promise<void>>();
  Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
  let undos: (() => void)[] = [];
  afterEach(() => {
    write.mockReset();
    undos.forEach((u) => u());
    undos = [];
  });
  const flush = () => new Promise((r) => setTimeout(r, 0));

  it("enables and wires the four Copy buttons, only the server Copy link's title dropped (Live pass, D1), chat and widgets named apart; Reset stays disabled; undo disables them again", () => {
    const d = load();
    const undo = bindStreamCopy(d, () => SETTINGS, true);
    for (const c of ["server", "key", "chat", "widgets"]) {
      const b = copyBtn(d, c);
      expect(b, c).toBeTruthy();
      expect(b.disabled).toBe(false);
      expect(b.hasAttribute("data-oi-wired")).toBe(true);
      if (c === "server") expect(b.hasAttribute("title"), c).toBe(false);
      else expect(b.title, c).toBe(NOT_YET);
      expect(b.getAttribute("aria-label"), c).toBe(LINK_NAMES[c as StreamCopy] ?? null);
    }
    expect(LINK_NAMES).toEqual({ chat: "Copy stream chat link", widgets: "Copy OBS widgets link" });
    const reset = [...d.querySelectorAll<HTMLButtonElement>("#content button")].find((b) => b.textContent?.trim() === "Reset")!;
    expect(reset.disabled).toBe(true);
    undo();
    expect(d.querySelectorAll("button[data-oi-stream-copy]")).toHaveLength(0);
    const copies = [...d.querySelectorAll<HTMLButtonElement>("#content button")].filter((b) => /^Copy (link|key)$/.test(b.textContent?.trim() ?? ""));
    expect(copies.map((b) => [b.disabled, b.title, b.hasAttribute("aria-label")])).toEqual(Array(4).fill([true, NOT_YET, false]));
  });

  it.each([
    ["server", SERVER, LINK_COPIED],
    ["key", KEY, KEY_COPIED],
    ["chat", CHAT, LINK_COPIED],
    ["widgets", "https://obs-settings.onlyfans.com/", LINK_COPIED],
  ])("%s copies its value and toasts; the key never enters the DOM", async (c, text, shown) => {
    write.mockResolvedValue();
    const d = load();
    undos.push(bindStreamCopy(d, () => SETTINGS, true));
    copyBtn(d, c).click();
    await flush();
    expect(write).toHaveBeenCalledWith(text);
    expect(d.getElementById("oi-toast")?.textContent).toBe(shown);
    expect(d.documentElement.outerHTML).not.toContain(KEY);
  });

  it("All Creators: Copy key notes Select a model and copies nothing; Copy link still copies", async () => {
    write.mockResolvedValue();
    const d = load();
    undos.push(bindStreamCopy(d, () => SETTINGS, false));
    copyBtn(d, "key").click();
    await flush();
    expect(write).not.toHaveBeenCalled();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    copyBtn(d, "server").click();
    await flush();
    expect(write).toHaveBeenCalledWith(SERVER);
  });

  it("a refused clipboard gives the error note", async () => {
    write.mockRejectedValue(new Error("denied"));
    const d = load();
    undos.push(bindStreamCopy(d, () => SETTINGS, true));
    copyBtn(d, "key").click();
    await flush();
    expect(d.getElementById("oi-note")?.textContent).toBe(NO_KEY);
  });
});

describe("bindStreamCopy: OBS server dropdown", () => {
  const MUX = { ...SETTINGS, streamingMuxServer: "rtmp://mux.synthetic.invalid/live", streamingMuxDirectKey: "oi-synthetic-mux-key-test" };
  const load = () => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/streaming.html"), "utf8");
    return document;
  };
  const write = vi.fn<(t: string) => Promise<void>>();
  beforeEach(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true }));
  const flush = () => new Promise((r) => setTimeout(r, 0));
  const dropdown = (d: Document) => d.getElementById("input-677") as HTMLInputElement;
  const pick = (d: Document, v: string) => {
    d.querySelector<HTMLElement>("label[for=input-677]")!.click();
    d.querySelector<HTMLElement>(`#oi-menu [data-oi-value='${v}']`)!.click();
  };

  it("enables and wires the dropdown, title dropped (Live pass, D1); its Server and Stream Key fields stay disabled and titled, named apart; unbind disables it, title and names back", () => {
    const d = load();
    const fields = ["input-677", "input-686", "input-689"].map((id) => d.getElementById(id) as HTMLInputElement);
    const state = () => fields.map((f) => [f.disabled, f.getAttribute("title"), f.getAttribute("aria-label")]);
    expect(state()).toEqual(Array(3).fill([true, NOT_YET, null]));
    const undo = bindStreamCopy(d, () => MUX, true);
    expect(dropdown(d).hasAttribute("data-oi-wired")).toBe(true);
    expect(FIELD_NAMES).toEqual({ Server: "Stream server address", "Stream Key": "Stream key" });
    expect(state()).toEqual([[false, null, null], [true, NOT_YET, "Stream server address"], [true, NOT_YET, "Stream key"]]);
    undo();
    expect(dropdown(d).hasAttribute("data-oi-wired")).toBe(false);
    expect(state()).toEqual(Array(3).fill([true, NOT_YET, null]));
  });

  it("a pick switches the shown server and the Copy buttons follow it; the keys never enter the DOM", async () => {
    write.mockReset();
    write.mockResolvedValue();
    const d = load();
    const undo = bindStreamCopy(d, () => MUX, true);
    pick(d, "mux_direct");
    expect(d.querySelector("#content .v-select__selection")?.textContent).toBe("OBS Server");
    expect((d.getElementById("input-686") as HTMLInputElement).value).toBe(MUX.streamingMuxServer);
    expect(d.getElementById("input-686")?.getAttribute("data-oi-obs-pair")).toBe("mux_direct");
    d.querySelector<HTMLButtonElement>("button[data-oi-stream-copy='server']")!.click();
    await flush();
    expect(write).toHaveBeenLastCalledWith(MUX.streamingMuxServer);
    d.querySelector<HTMLButtonElement>("button[data-oi-stream-copy='key']")!.click();
    await flush();
    expect(write).toHaveBeenLastCalledWith(MUX.streamingMuxDirectKey);
    pick(d, "obs_agora");
    d.querySelector<HTMLButtonElement>("button[data-oi-stream-copy='server']")!.click();
    await flush();
    expect(write).toHaveBeenLastCalledWith(SERVER);
    expect(d.documentElement.outerHTML).not.toContain("oi-synthetic-");
    undo();
  });

  it.each([
    ["server", "rtmp://mux.synthetic.invalid/live", true],
    ["key", "oi-synthetic-mux-key-test", true],
    ["server", "rtmp://mux.synthetic.invalid/live", false],
  ])("streamCopy %s follows mux_direct (selected %s)", (c, text, selected) => {
    expect(streamCopy(c as StreamCopy, MUX, null, selected, "mux_direct")).toEqual({ text, toast: c === "key" ? KEY_COPIED : LINK_COPIED });
  });
});

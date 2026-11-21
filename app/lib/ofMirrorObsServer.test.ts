import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { drawObsServer, OBS_SERVERS, obsPair, obsSelect, shownObsServer, STREAM_KEY_MASK } from "./ofMirrorObsServer";

const SETTINGS = {
  streamingRtmpServer: "rtmp://agora.synthetic.invalid/live", streamingRtmpKey: "oi-synthetic-agora-key",
  streamingMuxServer: " rtmp://mux.synthetic.invalid/live ", streamingMuxDirectKey: "oi-synthetic-mux-key",
};

describe("obsPair", () => {
  it.each<[string, unknown, string | null | undefined, { server: string; key: string }]>([
    ["obs_agora", SETTINGS, "obs_agora", { server: SETTINGS.streamingRtmpServer, key: SETTINGS.streamingRtmpKey }],
    ["mux_direct (trimmed)", SETTINGS, "mux_direct", { server: "rtmp://mux.synthetic.invalid/live", key: SETTINGS.streamingMuxDirectKey }],
    ["an unknown choice reads as obs_agora", SETTINGS, "other", { server: SETTINGS.streamingRtmpServer, key: SETTINGS.streamingRtmpKey }],
    ["no choice reads as obs_agora", SETTINGS, null, { server: SETTINGS.streamingRtmpServer, key: SETTINGS.streamingRtmpKey }],
    ["mux_direct with no key (OF's null)", { streamingMuxServer: "rtmp://m", streamingMuxDirectKey: null }, "mux_direct", { server: "rtmp://m", key: "" }],
    ["before the read lands", undefined, "mux_direct", { server: "", key: "" }],
  ])("%s", (_, settings, server, want) => {
    expect(obsPair(settings, server)).toEqual(want);
  });

  it("offers OF's two choices, obs_agora first", () => {
    expect(OBS_SERVERS.map((o) => [o.value, o.label])).toEqual([["obs_agora", "OBS CloudBeta"], ["mux_direct", "OBS Server"]]);
  });
});

describe("drawObsServer", () => {
  const load = () => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/streaming.html"), "utf8");
    return document;
  };
  const field = (d: Document, label: string) => {
    const l = [...d.querySelectorAll<HTMLLabelElement>("#content label.v-label")].find((x) => x.textContent?.trim() === label)!;
    return d.getElementById(l.htmlFor) as HTMLInputElement;
  };

  it("finds the captured select showing obs_agora", () => {
    const d = load();
    expect(obsSelect(d)?.querySelector(".v-select__selection")?.textContent).toBe("OBS CloudBeta");
    expect(shownObsServer(d)).toBe("obs_agora");
  });

  it("each choice shows its server and keeps the key masked; no key text in the DOM", () => {
    const d = load();
    for (const o of OBS_SERVERS) {
      drawObsServer(d, SETTINGS, o.value);
      expect(shownObsServer(d)).toBe(o.value);
      expect(obsSelect(d)?.querySelector(".v-select__selection")?.textContent).toBe(o.label);
      expect(field(d, "Server").value).toBe(obsPair(SETTINGS, o.value).server);
      expect(field(d, "Server").getAttribute("data-oi-obs-pair")).toBe(o.value);
      expect(field(d, "Server").getAttribute("data-oi-obs-shown")).toBe(o.value);
      expect(field(d, "Stream Key").value).toBe(STREAM_KEY_MASK);
      expect(d.documentElement.outerHTML).not.toContain("oi-synthetic-");
    }
  });

  it("a pair with no server shows an empty Server field, no pair marker, still marked shown", () => {
    const d = load();
    drawObsServer(d, SETTINGS, "obs_agora");
    drawObsServer(d, { ...SETTINGS, streamingMuxServer: " " }, "mux_direct");
    expect(field(d, "Server").value).toBe("");
    expect(field(d, "Server").hasAttribute("data-oi-obs-pair")).toBe(false);
    expect(field(d, "Server").getAttribute("data-oi-obs-shown")).toBe("mux_direct");
  });

  it("a redraw keeps the shown choice; a pair with no key shows an empty key field; no read leaves the fields", () => {
    const d = load();
    drawObsServer(d, SETTINGS, "mux_direct");
    drawObsServer(d, { ...SETTINGS, streamingMuxDirectKey: "" });
    expect(shownObsServer(d)).toBe("mux_direct");
    expect(field(d, "Stream Key").value).toBe("");
    const before = field(d, "Server").value;
    drawObsServer(d, undefined, "obs_agora");
    expect(field(d, "Server").value).toBe(before);
    expect(shownObsServer(d)).toBe("obs_agora");
  });
});

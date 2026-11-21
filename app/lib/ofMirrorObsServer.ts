/**
 * Settings › Streaming's OBS server dropdown (ticket 72, docs/spec/ofm-not-yet/phase-03-settings-privacy-links.md story
 * 21). Its capture record (.scratch/ofm-not-yet/captures/settings--streaming-obs-server-dropdown.json, settings-streaming.js)
 * shows a display switch: OF's v-model `selectedServer` is a local ref over two choices, obs_agora and mux_direct, each
 * showing its own pair from the settings read already made (obs_agora: streamingRtmpServer / streamingRtmpKey; mux_direct:
 * streamingMuxServer / streamingMuxDirectKey). No request is sent. The shown choice lives in the select's hidden input
 * (OF's own markup), so the Copy buttons (ofMirrorStreamCopy) follow it. The key never enters the page: its field shows
 * the mask while the shown pair has one.
 *
 * ASSUMPTION: mux_direct's label is "OBS Server" (the spec's story 21 names the two choices "OBS Server / OBS
 * CloudBeta"; obs_agora's "OBS CloudBeta" is the captured page's selection). Overturned by a capture of the open menu.
 */
import { objectOf } from "@/lib/ofMirrorDom";

export const STREAM_KEY_MASK = "•".repeat(16);

export type ObsServer = "obs_agora" | "mux_direct";

/** OF's two choices, menu order, each with its settings fields. */
export const OBS_SERVERS: { value: ObsServer; label: string; server: string; key: string }[] = [
  { value: "obs_agora", label: "OBS CloudBeta", server: "streamingRtmpServer", key: "streamingRtmpKey" },
  { value: "mux_direct", label: "OBS Server", server: "streamingMuxServer", key: "streamingMuxDirectKey" },
];

const choice = (server: string | null | undefined) => OBS_SERVERS.find((o) => o.value === server) ?? OBS_SERVERS[0];

/** The shown choice's server and key in the settings read (trimmed; "" when absent). Unknown choices read as obs_agora. */
export function obsPair(settings: unknown, server: string | null | undefined): { server: string; key: string } {
  const s = objectOf<Record<string, unknown>>(settings) ?? {};
  const o = choice(server);
  const value = (v: unknown) => (typeof v === "string" ? v.trim() : "");
  return { server: value(s[o.server]), key: value(s[o.key]) };
}

/** The OBS server select (`.v-select` labelled "OBS Server"), or null. */
export function obsSelect(doc: Document): HTMLElement | null {
  const label = [...doc.querySelectorAll<HTMLLabelElement>("#content .v-select label.v-label")].find((l) => l.textContent?.trim() === "OBS Server");
  return label?.closest<HTMLElement>(".v-select") ?? null;
}

/** The choice the page shows (the select's hidden input), obs_agora when none. */
export function shownObsServer(doc: Document): ObsServer {
  return choice(obsSelect(doc)?.querySelector<HTMLInputElement>("input[type='hidden']")?.value).value;
}

/** The page's field labelled `text` ("Server", "Stream Key"), or null. */
export const fieldByLabel = (doc: Document, text: string) => {
  const label = [...doc.querySelectorAll<HTMLLabelElement>("#content label.v-label")].find((l) => l.textContent?.trim() === text);
  return label?.htmlFor ? (doc.getElementById(label.htmlFor) as HTMLInputElement | null) : null;
};

/**
 * Show `server` (default: the shown choice) in the select, its Server field and the Stream Key mask. `settings`: the
 * settings read (undefined until it lands: the Server field is left as it is). The Server field's
 * `data-oi-obs-pair` names the choice whose server it shows (none while it shows none); `data-oi-obs-shown` names the
 * choice drawn from the read, empty server or not (an account that never streamed has none): the dropdown's Live proof
 * waits for it (scripts/of-live-proof/proofs/phase3.py, settings--streaming-obs-server-dropdown). Idempotent.
 */
export function drawObsServer(doc: Document, settings: unknown, server: ObsServer = shownObsServer(doc)): void {
  const sel = obsSelect(doc);
  const o = choice(server);
  const shown = sel?.querySelector(".v-select__selection");
  if (shown) shown.textContent = o.label;
  const hidden = sel?.querySelector<HTMLInputElement>("input[type='hidden']");
  if (hidden) hidden.value = o.value;
  if (objectOf(settings) === null) return;
  const pair = obsPair(settings, o.value);
  const serverField = fieldByLabel(doc, "Server");
  if (serverField) {
    serverField.value = pair.server;
    if (pair.server) serverField.setAttribute("data-oi-obs-pair", o.value);
    else serverField.removeAttribute("data-oi-obs-pair");
    serverField.setAttribute("data-oi-obs-shown", o.value);
  }
  const keyField = fieldByLabel(doc, "Stream Key");
  if (keyField) keyField.value = pair.key ? STREAM_KEY_MASK : "";
}

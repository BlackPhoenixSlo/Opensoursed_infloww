import { objectOf } from "@/lib/ofMirrorDom";

// The key never enters the page: the field shows only the mask.
export const STREAM_KEY_MASK = "•".repeat(16);

export type ObsServer = "obs_agora" | "mux_direct";

export const OBS_SERVERS: { value: ObsServer; label: string; server: string; key: string }[] = [
  { value: "obs_agora", label: "OBS CloudBeta", server: "streamingRtmpServer", key: "streamingRtmpKey" },
  { value: "mux_direct", label: "OBS Server", server: "streamingMuxServer", key: "streamingMuxDirectKey" },
];

const choice = (server: string | null | undefined) => OBS_SERVERS.find((o) => o.value === server) ?? OBS_SERVERS[0];

export function obsPair(settings: unknown, server: string | null | undefined): { server: string; key: string } {
  const s = objectOf<Record<string, unknown>>(settings) ?? {};
  const o = choice(server);
  const value = (v: unknown) => (typeof v === "string" ? v.trim() : "");
  return { server: value(s[o.server]), key: value(s[o.key]) };
}

export function obsSelect(doc: Document): HTMLElement | null {
  const label = [...doc.querySelectorAll<HTMLLabelElement>("#content .v-select label.v-label")].find((l) => l.textContent?.trim() === "OBS Server");
  return label?.closest<HTMLElement>(".v-select") ?? null;
}

export function shownObsServer(doc: Document): ObsServer {
  return choice(obsSelect(doc)?.querySelector<HTMLInputElement>("input[type='hidden']")?.value).value;
}

export const fieldByLabel = (doc: Document, text: string) => {
  const label = [...doc.querySelectorAll<HTMLLabelElement>("#content label.v-label")].find((l) => l.textContent?.trim() === text);
  return label?.htmlFor ? (doc.getElementById(label.htmlFor) as HTMLInputElement | null) : null;
};

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

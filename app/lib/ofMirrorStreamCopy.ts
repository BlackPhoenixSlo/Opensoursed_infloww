import { useEffect, type RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { toast } from "@/lib/ofMirrorToast";
import { mirrorPageOfPath } from "@/lib/of-mirror-route";
import { note, NOT_YET, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { closeMenu, showMenu } from "@/lib/ofMirrorMenu";
import { drawObsServer, fieldByLabel, OBS_SERVERS, obsPair, obsSelect, shownObsServer, type ObsServer } from "@/lib/ofMirrorObsServer";

export type StreamCopy = "server" | "key" | "chat" | "widgets";
export type StreamCopyResult = { text: string; toast: string } | { note: string; error: boolean };

export const PAGE = "settings/streaming";
export const LINK_COPIED = "Link copied";
export const KEY_COPIED = "Copied to clipboard";
export const NO_LINK = "Could not copy the link";
export const NO_KEY = "Could not copy the key";

export function streamCopy(control: StreamCopy, settings: unknown, link: string | null, selected: boolean, server: ObsServer = "obs_agora"): StreamCopyResult {
  const pair = obsPair(settings, server);
  if (control === "key") {
    // A stand-in's key pasted into OBS would stream on a Creator the operator did not pick.
    if (!selected) return { note: SELECT_MODEL, error: false };
    return pair.key ? { text: pair.key, toast: KEY_COPIED } : { note: NO_KEY, error: true };
  }
  const text = control === "server" ? pair.server : typeof link === "string" ? link.trim() : "";
  return text ? { text, toast: LINK_COPIED } : { note: NO_LINK, error: true };
}

export const LINK_NAMES: Partial<Record<StreamCopy, string>> = { chat: "Copy stream chat link", widgets: "Copy OBS widgets link" };

export const FIELD_NAMES: Record<string, string> = { Server: "Stream server address", "Stream Key": "Stream key" };

function buttons(doc: Document): [HTMLButtonElement, StreamCopy][] {
  const out: [HTMLButtonElement, StreamCopy][] = [];
  for (const row of doc.querySelectorAll<HTMLElement>("#content .b-settings__spacer")) {
    const label = row.querySelector("label.v-label")?.textContent?.trim();
    const link = row.querySelector("a.b-field-like")?.textContent?.trim() ?? "";
    const control: StreamCopy | null =
      label === "Server" ? "server" : label === "Stream Key" ? "key"
        : link.endsWith("/my/streaming/chat") ? "chat" : link.startsWith("https://obs-settings.") ? "widgets" : null;
    const btn = [...row.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === (control === "key" ? "Copy key" : "Copy link"));
    if (control && btn) out.push([btn, control]);
  }
  return out;
}

function obsUsable(sel: HTMLElement, on: boolean): void {
  sel.querySelector("[aria-owns]")?.setAttribute("aria-disabled", String(!on));
  const field = sel.querySelector<HTMLInputElement>("input:not([type='hidden'])");
  for (const el of [sel, field]) el?.toggleAttribute("data-oi-wired", on);
  if (!field) return;
  field.disabled = !on;
  if (on) field.removeAttribute("title");
  else field.setAttribute("title", NOT_YET);
}

function nameFields(doc: Document, on: boolean): void {
  for (const [label, name] of Object.entries(FIELD_NAMES)) {
    const f = fieldByLabel(doc, label);
    if (on) f?.setAttribute("aria-label", name);
    else f?.removeAttribute("aria-label");
  }
}

export function bindStreamCopy(doc: Document, settings: () => unknown, selected: boolean): () => void {
  const found = buttons(doc);
  const titles = found.map(([b]) => b.getAttribute("title"));
  for (const [b, control] of found) {
    b.disabled = false;
    b.setAttribute("data-oi-wired", "");
    b.setAttribute("data-oi-stream-copy", control);
    if (control === "server") b.removeAttribute("title");
    const name = LINK_NAMES[control];
    if (name) b.setAttribute("aria-label", name);
  }
  const obs = obsSelect(doc);
  if (obs) {
    obsUsable(obs, true);
    nameFields(doc, true);
  }
  const onClick = (ev: MouseEvent) => {
    if (obs?.contains(ev.target as Node)) {
      ev.preventDefault();
      const options = OBS_SERVERS.map((o) => ({ value: o.value, label: o.label }));
      showMenu(doc, obs, [{ name: "obs-server", radio: false, value: shownObsServer(doc), options }], (_g, v) => {
        drawObsServer(doc, settings(), v as ObsServer);
      });
      return;
    }
    const b = (ev.target as Element | null)?.closest?.<HTMLButtonElement>("button[data-oi-stream-copy]");
    if (!b) return;
    ev.preventDefault();
    const control = b.getAttribute("data-oi-stream-copy") as StreamCopy;
    const link = b.closest(".b-settings__spacer")?.querySelector("a.b-field-like")?.textContent ?? null;
    const r = streamCopy(control, settings(), link, selected, shownObsServer(doc));
    if ("note" in r) return note(doc, b, r.note, r.error);
    const fail = control === "key" ? NO_KEY : NO_LINK;
    const clipboard = doc.defaultView?.navigator.clipboard;
    if (!clipboard) return note(doc, b, fail, true);
    clipboard.writeText(r.text).then(
      () => void toast(doc, r.toast),
      () => note(doc, b, fail, true),
    );
  };
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("click", onClick);
    if (obs) {
      closeMenu(doc);
      obsUsable(obs, false);
      nameFields(doc, false);
    }
    found.forEach(([b, control], i) => {
      b.disabled = true;
      b.removeAttribute("data-oi-wired");
      b.removeAttribute("data-oi-stream-copy");
      if (LINK_NAMES[control]) b.removeAttribute("aria-label");
      if (titles[i] !== null) b.setAttribute("title", titles[i]!);
    });
  };
}

export function useOfStreamCopy(frameRef: RefObject<HTMLIFrameElement | null>, src: string, standIn: string | null): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const on = mirrorPageOfPath(src) === PAGE;
  const selected = !standIn && !!accountId;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    const settings = () => qc.getQueryData(["of-settings", "settings", accountId]);
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindStreamCopy(doc, settings, selected) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, on, qc, accountId, selected]);
}

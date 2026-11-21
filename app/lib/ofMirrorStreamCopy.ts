/**
 * Settings › Streaming's four Copy buttons (ticket 59, docs/spec/ofm-not-yet/phase-03-settings-privacy-links.md): Copy
 * link beside the Server puts the shown OBS server's server on the clipboard, Copy key its key (ticket 72: the pair the
 * OBS server dropdown shows, ofMirrorObsServer), and the Copy links beside the stream chat and OBS widgets links their
 * OnlyFans URLs (the link's own text). The values come from the settings read useOfSettings already made (its query
 * cache entry, read on click): no new request, no write. The key goes to the clipboard only, never into the page (the
 * Stream Key field keeps the mask).
 *
 * ticket 72: the OBS server dropdown is bound here too (enabled, Wired): a pick shows that choice's pair
 * (drawObsServer), a display switch with no request, as its capture record shows. Its Live proof passed (D1, 2026-11-21,
 * docs/of-manager/captures/settings--streaming-obs-server-dropdown.json, sweep label "[INPUT]"): the Not-yet title drops
 * from its field. The Server and Stream Key fields it fills have no Live proof of their own: they stay disabled with
 * the title, named apart while bound (FIELD_NAMES) so the sweep's "[INPUT]" is the dropdown's alone.
 *
 * All Creators (a stand-in bound, or no model): Copy key gives the Select-model note and copies nothing, as a stand-in's
 * key pasted into OBS would stream on a Creator the operator did not pick (ticket 59's ASSUMPTION); Copy link copies
 * the server the page shows (the stand-in's). Reset is ofMirrorSettingsWrites' (ticket 76). Only the server's Copy link
 * drops its Not-yet title (D1: sweep label "Copy link", capture record
 * docs/of-manager/captures/settings--streaming-copy-link.json, 2026-11-21, story 22). Copy key and the stream chat and
 * OBS widgets Copy links (story 25, no Live proof yet) keep it; those two carry their own accessible names (LINK_NAMES)
 * so the sweep tells them from the server's.
 *
 * ASSUMPTION: the toasts are "Link copied" (tracking-link Copy's) and, for the key, "Copied to clipboard" (the message
 * menu's); OnlyFans's own Streaming texts are not captured. Overturned by a capture of them.
 */
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

/**
 * What a Copy click copies, or the note it shows instead. `settings`: the /users/me/settings read (undefined until it
 * lands); `link`: the stream chat or widgets link's text; `selected`: a single model is picked (no stand-in); `server`:
 * the OBS server choice the page shows (ticket 72).
 */
export function streamCopy(control: StreamCopy, settings: unknown, link: string | null, selected: boolean, server: ObsServer = "obs_agora"): StreamCopyResult {
  const pair = obsPair(settings, server);
  if (control === "key") {
    if (!selected) return { note: SELECT_MODEL, error: false };
    return pair.key ? { text: pair.key, toast: KEY_COPIED } : { note: NO_KEY, error: true };
  }
  const text = control === "server" ? pair.server : typeof link === "string" ? link.trim() : "";
  return text ? { text, toast: LINK_COPIED } : { note: NO_LINK, error: true };
}

/**
 * The stream chat and OBS widgets Copy links' accessible names (aria-label, while bound): all three Copy links read "Copy
 * link" on screen, and the sweep labels a control by its aria-label first, so only the server's stays "Copy link".
 */
export const LINK_NAMES: Partial<Record<StreamCopy, string>> = { chat: "Copy stream chat link", widgets: "Copy OBS widgets link" };

/**
 * The Server and Stream Key fields' accessible names (aria-label, while bound), by their visible label: the sweep labels
 * an unnamed input "[INPUT]", the dropdown's sweep label, so only the dropdown's field keeps it.
 */
export const FIELD_NAMES: Record<string, string> = { Server: "Stream server address", "Stream Key": "Stream key" };

/** Each Copy button's control, by the field its row holds. */
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

/**
 * The OBS server select's text field (OF's dropdown input) usable or not, Wired while usable: enabled with no title, or
 * disabled with the Not-yet title (never disabled untitled).
 */
function obsUsable(sel: HTMLElement, on: boolean): void {
  sel.querySelector("[aria-owns]")?.setAttribute("aria-disabled", String(!on));
  const field = sel.querySelector<HTMLInputElement>("input:not([type='hidden'])");
  for (const el of [sel, field]) el?.toggleAttribute("data-oi-wired", on);
  if (!field) return;
  field.disabled = !on;
  if (on) field.removeAttribute("title");
  else field.setAttribute("title", NOT_YET);
}

/** The Server and Stream Key fields named apart (FIELD_NAMES) or not; disabled and titled either way. */
function nameFields(doc: Document, on: boolean): void {
  for (const [label, name] of Object.entries(FIELD_NAMES)) {
    const f = fieldByLabel(doc, label);
    if (on) f?.setAttribute("aria-label", name);
    else f?.removeAttribute("aria-label");
  }
}

/**
 * Streaming's Copy buttons in `doc` enabled and Wired (`data-oi-stream-copy` names the control), the server Copy link's
 * title dropped (Live pass, D1), the others' kept, the chat and widgets ones named (LINK_NAMES), and the OBS server
 * dropdown (ticket 72; its Server and Stream Key fields named, FIELD_NAMES). `settings()` reads the settings on click.
 * Returns an unbind that disables them again, titles restored and names removed.
 */
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

/**
 * Settings › Streaming in the frame: its Copy buttons, on every load. `standIn`: the stand-in Creator the page shows in
 * All Creators (OfMirrorFrame's), null when a model is picked.
 */
export function useOfStreamCopy(frameRef: RefObject<HTMLIFrameElement | null>, src: string, standIn: string | null): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const on = mirrorPageOfPath(src) === PAGE;
  const selected = !standIn && !!accountId;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    // useOfSettings's cache entry for this page's settings read (its query key), read on click only.
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

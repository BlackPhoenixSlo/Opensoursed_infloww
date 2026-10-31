"use client";

/**
 * The Mirror frame's chrome: OF's toast (toast), carried over a frame navigation (frameNavigate, takeCarried), a disabled
 * tool (lock) and the "not supported here" Record popup (recordPopup). ofMirrorPost re-exports its public names.
 */

import type { RefObject } from "react";
import { mirrorPageOfHref, mirrorPageOfPath } from "@/lib/of-mirror-route";

/** How long OF's toast stays. */
const TOAST_MS = 5_000;

/** A tool OF disables (`on`) or enables again: a mirror link takes no click while disabled. */
export function lock(el: HTMLElement, on: boolean): void {
  el.toggleAttribute("disabled", on);
  el.setAttribute("aria-disabled", String(on));
  el.style.pointerEvents = on ? "none" : "";
  el.style.opacity = on ? "0.4" : "";
}

/**
 * OF's toast (its `.toasts-host`, made when the page has none, and a `v-snack m-alert` without a timer bar) saying `text`;
 * it goes after TOAST_MS. Returns the toast.
 */
export function toast(doc: Document, text: string): HTMLElement {
  let host = doc.querySelector<HTMLElement>(".toasts-host");
  if (!host) {
    host = doc.createElement("div");
    host.className = "toasts-host w-100 h-100 d-flex flex-column-reverse justify-content-start";
    host.style.cssText = "top:0;left:0";
    doc.body.append(host);
  }
  const snack = doc.createElement("div");
  snack.className = "v-snack v-snack--active v-snack--bottom v-snack--has-background m-alert";
  snack.id = "oi-toast";
  snack.innerHTML = '<div class="v-snack__wrapper v-sheet theme--dark"><div role="status" aria-live="polite" class="v-snack__content m-without-timer"><div class="toast__body"><div class="toast__content"><div class="toast__text"></div></div></div></div></div>';
  snack.querySelector(".toast__text")!.textContent = text;
  doc.getElementById("oi-toast")?.remove();
  host.append(snack);
  doc.defaultView?.setTimeout(() => snack.remove(), TOAST_MS);
  return snack;
}

/** How long a carried toast waits for its page's document (it never shows late, on a page opened again). */
export const CARRY_MS = 15_000;
/** A toast carried over a navigation: the mirror page it shows on, the one it was carried from, its text and expiry. */
let carried: { page: string; from: string | null; text: string; until: number } | null = null;
/** A document's mirror page, its path under of-mirror/pages; null for about:blank (a new frame's placeholder). */
const docPage = (doc: Document) => mirrorPageOfPath(doc.location?.pathname ?? "");

/**
 * OF's toast `text`, carried to the page an /of-manager `href` opens (its mirror page, as the route maps it: the section
 * root is its index page). `current` (the frame's document now) already that page: the toast shows at once and this
 * returns true (nothing to navigate); so does an empty `href` (no destination: it shows where the user is). Else it waits
 * CARRY_MS for that page's bind (takeCarried).
 */
function carryToast(current: Document | null | undefined, href: string, text: string): boolean {
  const page = mirrorPageOfHref(href);
  const here = current ? docPage(current) : null;
  if (current?.body && (!href || (page !== null && here === page))) return toast(current, text), true;
  carried = page ? { page, from: here, text, until: Date.now() + CARRY_MS } : null;
  return false;
}

/**
 * A binder's first step on `doc`: the carried toast shows if `doc` is its page. about:blank and the page it was carried
 * from (a rebind there while the frame loads) keep it; any other page, or its expiry, drops it.
 */
export function takeCarried(doc: Document): void {
  const here = docPage(doc);
  if (!carried || !here) return;
  const live = Date.now() < carried.until;
  if (live && here === carried.from) return;
  if (live && here === carried.page) toast(doc, carried.text);
  carried = null;
}

/** A binder's navigate(href, toast?) for the frame: `toast` carried to href's page (carryToast), and router.push unless it is there already. */
export const frameNavigate =
  (frameRef: RefObject<HTMLIFrameElement | null>, push: (href: string) => void) =>
  (href: string, text?: string): void => {
    if (!text || !carryToast(frameRef.current?.contentDocument, href, text)) push(href);
  };

/** The Record popup's id and its text. */
const RECORD_POPUP = "oi-record-popup";
export const RECORD_TEXT = "Recording isn't supported here. Use OnlyFans in your real browser. (I am a lazy dev.)";

/** A small OF dialog saying recording is not supported here, with an OK that closes it (as does its backdrop). */
export function recordPopup(doc: Document, closed?: () => void): HTMLElement {
  doc.getElementById(RECORD_POPUP)?.remove();
  const root = doc.createElement("div");
  root.id = RECORD_POPUP;
  root.setAttribute("data-oi-wired", "");
  root.innerHTML =
    '<div class="modal fade show" role="dialog" aria-modal="true" style="display:block;z-index:1050">' +
    '<div class="modal-dialog modal-sm modal-dialog-centered"><div class="modal-content">' +
    '<div class="modal-body"><p class="m-break-word" style="margin:16px 0 0"></p></div>' +
    '<div class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-wired="" data-oi-ok=""> OK </button></div>' +
    '</div></div></div><div class="modal-backdrop fade show" data-oi-ok="" style="z-index:1040"></div>';
  root.querySelector("p")!.textContent = RECORD_TEXT;
  root.addEventListener("click", (ev) => {
    if (!(ev.target as Element).closest("[data-oi-ok]")) return;
    root.remove();
    closed?.();
  });
  doc.body.append(root);
  root.querySelector<HTMLButtonElement>("[data-oi-ok]")?.focus();
  return root;
}

/** For ofMirrorPost only; not re-exported. */
export { RECORD_POPUP };

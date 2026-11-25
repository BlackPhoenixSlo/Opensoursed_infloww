"use client";


import type { RefObject } from "react";
import { mirrorPageOfHref, mirrorPageOfPath } from "@/lib/of-mirror-route";

const TOAST_MS = 5_000;

export function lock(el: HTMLElement, on: boolean): void {
  el.toggleAttribute("disabled", on);
  el.setAttribute("aria-disabled", String(on));
  el.style.pointerEvents = on ? "none" : "";
  el.style.opacity = on ? "0.4" : "";
}

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

export const CARRY_MS = 15_000;
let carried: { page: string; from: string | null; text: string; until: number } | null = null;
const docPage = (doc: Document) => mirrorPageOfPath(doc.location?.pathname ?? "");

function carryToast(current: Document | null | undefined, href: string, text: string): boolean {
  const page = mirrorPageOfHref(href);
  const here = current ? docPage(current) : null;
  if (current?.body && (!href || (page !== null && here === page))) return toast(current, text), true;
  carried = page ? { page, from: here, text, until: Date.now() + CARRY_MS } : null;
  return false;
}

export function takeCarried(doc: Document): void {
  const here = docPage(doc);
  if (!carried || !here) return;
  const live = Date.now() < carried.until;
  if (live && here === carried.from) return;
  if (live && here === carried.page) toast(doc, carried.text);
  carried = null;
}

export const frameNavigate =
  (frameRef: RefObject<HTMLIFrameElement | null>, push: (href: string) => void) =>
  (href: string, text?: string): void => {
    if (!text || !carryToast(frameRef.current?.contentDocument, href, text)) push(href);
  };

const RECORD_POPUP = "oi-record-popup";
export const RECORD_TEXT = "Recording isn't supported here. Use OnlyFans in your real browser. (I am a lazy dev.)";

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

export { RECORD_POPUP };

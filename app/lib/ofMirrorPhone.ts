"use client";


import { useEffect, type RefObject } from "react";
import { MODAL_VIEW, SM_QUERY } from "./ofMirrorMenu";

const XS_QUERY = "(max-width: 499.98px)";

const NAV_SCROLL = ["m-native-custom-scrollbar", "m-scrollbar-y", "m-invisible-scrollbar"];
const POST_BTN = ["g-btn", "m-rounded", "m-lg", "m-reset-width"];
const KEPT = ["m-avatar-item", "m-home", "m-notifications", "m-chats", "m-create-post"];

export function applyPhoneHeader(doc: Document, xs: boolean): void {
  const nav = doc.querySelector<HTMLElement>("nav.l-header__menu");
  if (!nav) return;
  nav.classList.toggle("g-sides-gaps", xs);
  for (const c of NAV_SCROLL) nav.classList.toggle(c, !xs);
  const avatar = nav.querySelector(".m-avatar-item .g-avatar");
  avatar?.classList.toggle("m-w24", xs);
  avatar?.classList.toggle("m-w36", !xs);
  for (const item of nav.querySelectorAll<HTMLElement>(":scope > .l-header__menu__item")) {
    if (KEPT.some((c) => item.classList.contains(c))) continue;
    item.style.display = xs ? "none" : "";
  }
  const post = nav.querySelector(".m-create-post");
  for (const c of POST_BTN) post?.classList.toggle(c, !xs);
}


function menuOverlay(doc: Document): HTMLElement {
  const el = doc.createElement("div");
  el.className = "v-menu-overlay";
  el.setAttribute("data-oi-phone-menu", "");
  return el;
}

const PHONE_MENU_STYLE: [string, string][] = [
  ["position", "fixed"],
  ["max-width", "100%"],
  ["min-width", "0"],
];

type Moved = HTMLElement & { _oiHome?: { parent: Node; next: Node | null; style: string | null }; _oiClick?: (ev: Event) => void };

export function applyPhoneMenus(doc: Document, phone: boolean): void {
  for (const menu of doc.querySelectorAll<Moved>(".of-state-menu.v-menu__content:not(.m-v-menu-mob)")) {
    if (phone && !menu._oiHome) {
      menu._oiHome = { parent: menu.parentNode!, next: menu.nextSibling, style: menu.getAttribute("style") };
      for (const [k, v] of PHONE_MENU_STYLE) menu.style.setProperty(k, v, "important");
      if (menu.classList.contains("m-dropdown-list")) {
        menu.classList.add(MODAL_VIEW);
        doc.body.append(menu);
      } else {
        menu.style.setProperty("z-index", "1042", "important");
        doc.body.append(menu, menuOverlay(doc));
      }
      menu._oiClick = (ev) => {
        if (ev.target === menu) doc.querySelector<HTMLElement>("a.of-state-backdrop")?.click();
      };
      menu.addEventListener("click", menu._oiClick);
    } else if (!phone && menu._oiHome) {
      const { parent, next, style } = menu._oiHome;
      const overlay = menu.nextElementSibling;
      if (overlay?.matches("[data-oi-phone-menu]")) overlay.remove();
      menu.classList.remove(MODAL_VIEW);
      parent.insertBefore(menu, next);
      if (style === null) menu.removeAttribute("style");
      else menu.setAttribute("style", style);
      if (menu._oiClick) menu.removeEventListener("click", menu._oiClick);
      delete menu._oiHome;
      delete menu._oiClick;
    }
  }
}

function bindQuery(doc: Document, query: string, apply: (doc: Document, on: boolean) => void): () => void {
  const mq = doc.defaultView?.matchMedia?.(query);
  if (!mq) return () => {};
  const run = () => apply(doc, mq.matches);
  run();
  mq.addEventListener?.("change", run);
  return () => mq.removeEventListener?.("change", run);
}

export function useOfPhone(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const setVh = () => {
      const win = frame.contentWindow;
      if (win?.innerHeight) frame.contentDocument?.documentElement.style.setProperty("--vh", `${0.01 * win.innerHeight}px`);
    };
    let unbind: (() => void) | undefined;
    const attach = () => {
      setVh();
      unbind?.();
      const doc = frame.contentDocument;
      const unbinds = doc ? [bindQuery(doc, XS_QUERY, applyPhoneHeader), bindQuery(doc, SM_QUERY, applyPhoneMenus)] : [];
      unbind = () => unbinds.forEach((f) => f());
      frame.contentWindow?.addEventListener("resize", setVh);
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      frame.contentWindow?.removeEventListener("resize", setVh);
      unbind?.();
    };
  }, [frameRef, src]);
}

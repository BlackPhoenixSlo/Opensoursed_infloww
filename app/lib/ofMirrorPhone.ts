"use client";

/**
 * OF's phone bar (WebsiteHeader below its XS breakpoint, 500px: app.js's media-query map). The mirror's pages are
 * desktop captures, so the frame does at run time what OF's template does on a phone (main.js WebsiteHeader, isXSMQ):
 * - the nav is "g-sides-gaps" instead of its scrollbar classes;
 * - the avatar item's avatar is 24px (m-w24) instead of 36px;
 * - only Home, Notifications and Messages stay of the nav items (OF renders the rest, and More, only above XS);
 * - New post is a plain item, not OF's "g-btn m-rounded m-lg m-reset-width" button.
 * Captured on the live phone view (390px, dpr 3, mobile): avatar, Home, Notifications, Messages, New post in the DOM,
 * laid out by OF's own CSS.
 * useOfPhone keeps both, and OF's --vh, on the frame's own size.
 */

import { useEffect, type RefObject } from "react";
import { MODAL_VIEW, SM_QUERY } from "./ofMirrorMenu";

/** OF's XS width (its breakpoint map: XS 500, SM 768, MD 1004). */
const XS_QUERY = "(max-width: 499.98px)";

const NAV_SCROLL = ["m-native-custom-scrollbar", "m-scrollbar-y", "m-invisible-scrollbar"];
const POST_BTN = ["g-btn", "m-rounded", "m-lg", "m-reset-width"];
const KEPT = ["m-avatar-item", "m-home", "m-notifications", "m-chats", "m-create-post"];

/** Lay the mirror's header out as OF's phone (xs) or desktop template does. Idempotent both ways. */
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

/**
 * OF's SM width: below it an open menu is a full-screen box with its list in the middle over the dimmed page (captured on
 * the live phone view, 390px):
 * - a Vuetify select's list: a body-level `v-menu__content` with a `v-menu-overlay` after it, laid out by app.css
 *   (`body:has(.v-menu-overlay) .v-menu__content:not(.m-v-menu-mob)`); the country picker, `m-v-menu-mob`, stays under
 *   its field;
 * - a sort dropdown (`m-dropdown-list`): the menu itself takes `m-modal-view`, which its scoped CSS (58702.css,
 *   `.v-menu__content.m-dropdown-list.m-modal-view[data-v-55f3fe86]`) makes the full-screen dimmed box; no overlay.
 * (SM_QUERY, MODAL_VIEW: ofMirrorMenu, whose sort menus open the same way.)
 */

/** The overlay OF puts after an open menu (its own class; app.css hides it at SM and up). */
function menuOverlay(doc: Document): HTMLElement {
  const el = doc.createElement("div");
  el.className = "v-menu-overlay";
  el.setAttribute("data-oi-phone-menu", "");
  return el;
}

/** The inline marks that beat a state page's `.of-state-menu` placement (its !important rules put it under its control). */
const PHONE_MENU_STYLE: [string, string][] = [
  ["position", "fixed"],
  ["max-width", "100%"],
  ["min-width", "0"],
];

type Moved = HTMLElement & { _oiHome?: { parent: Node; next: Node | null; style: string | null }; _oiClick?: (ev: Event) => void };

/**
 * A state page's open menu as OF's on a phone (`phone`) or back under its control. Idempotent both ways. A press on the
 * full-screen box outside the list follows the page's backdrop link, as OF's overlay closes the menu.
 */
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

/** Follow `doc`'s width: `apply` as OF's `query` matches, again on each change. Returns the unbind. */
function bindQuery(doc: Document, query: string, apply: (doc: Document, on: boolean) => void): () => void {
  const mq = doc.defaultView?.matchMedia?.(query);
  if (!mq) return () => {};
  const run = () => apply(doc, mq.matches);
  run();
  mq.addEventListener?.("change", run);
  return () => mq.removeEventListener?.("change", run);
}

/**
 * The frame's page as OF's at the frame's own size, on every frame load: OF's setVHVariable (main.js; --vh is 1% of the
 * window's inner height, kept on resize; the capture froze the capturing window's value in <html style>), its phone bar
 * below XS, and a state page's open menu as OF's below SM.
 */
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

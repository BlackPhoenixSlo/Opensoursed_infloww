"use client";

/**
 * OF's own left nav (header.l-header: avatar, Home ... More, NEW POST) hidden in the mirror frame, as Infloww hides it:
 * a stylesheet injected into the page at runtime (its preload pages/of/common.css, docs/infloww-of-manager-rea.md §1.9),
 * so the 385 mirror files stay as generated. The header stays in the DOM (identity badges, tests) but is invisible
 * and takes no clicks; OF's main column fills the width. Navigation is our sidebar's OF Manager submenu.
 */

import { useEffect, type RefObject } from "react";

export const OF_CHROME_STYLE_ID = "oi-of-chrome";

/** On the page's <html> while the Fan insights column lies over the frame's right 280px (OfManagerChrome). */
export const OF_INSIGHTS_ATTR = "data-oi-insights";

/** Infloww's rules, minus its Electron-only ones (-webkit-app-region, its fan-item hover colour); plus, for the
 *  mirror's fixed captures, no width caps on the right column and the two-pane pages (chats, vault, settings: OF caps
 *  them at 368px and 999px), so they run to the frame's edge as in Infloww's window rather than leaving the nav's gap,
 *  and no #content edge line where the nav ended. With the Fan insights column over the frame's right 280px, the chats
 *  page leaves it that room, as Infloww's column inside OF's `.b-chats__conversations` does: OF keeps its wide layout
 *  (the chat list beside the chat, from 1004px), which a frame narrowed by the column would drop. */
export const OF_CHROME_CSS = `
.l-header{position:absolute!important;pointer-events:none!important}
.l-header>nav{opacity:0!important;visibility:hidden!important}
#content{border-right:none!important;max-width:100%!important}
#content:after{display:none!important}
.l-wrapper__content{margin-left:0!important;max-width:100%}
.container{max-width:100%!important;padding:0!important}
.l-wrapper__sidebar{flex:1 0 300px!important;min-width:300px!important;max-width:none!important;margin-right:0!important;padding-right:16px!important}
.b-chats__conversations-list{max-width:345px!important;flex:0 0 345px!important}
.b-chats__conversations{max-width:100%!important}
html[${OF_INSIGHTS_ATTR}] .b-chats__conversations{padding-right:280px!important}
html[${OF_INSIGHTS_ATTR}] .b-chats__conversations-content{max-width:none!important}
#content>*{max-width:100%!important;margin-left:0!important}
.banner_place,.b-login-posts-wrapper,.l-footer-static,.b-login-posts-outer,.contact_button.visible-lg{display:none!important}
`;

/** Add the stylesheet to `doc` once; true once it is there. */
export function injectOfChrome(doc: Document | null | undefined): boolean {
  if (!doc?.head) return false;
  if (doc.getElementById(OF_CHROME_STYLE_ID)) return true;
  const style = doc.createElement("style");
  style.id = OF_CHROME_STYLE_ID;
  style.textContent = OF_CHROME_CSS;
  doc.head.appendChild(style);
  return true;
}

/** Hide OF's nav in the frame: as soon as the page's <head> parses (no flash of the nav), and again on every load. */
export function useOfChrome(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let raf = 0;
    const apply = () => {
      cancelAnimationFrame(raf);
      injectOfChrome(frame.contentDocument);
    };
    const poll = () => {
      const doc = frame.contentDocument;
      // The fresh frame starts on about:blank; wait for the mirror page's own document.
      if (doc && doc.URL !== "about:blank" && injectOfChrome(doc)) return;
      raf = requestAnimationFrame(poll);
    };
    poll();
    frame.addEventListener("load", apply);
    return () => {
      cancelAnimationFrame(raf);
      frame.removeEventListener("load", apply);
    };
  }, [frameRef, src]);
}

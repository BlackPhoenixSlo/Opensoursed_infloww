"use client";


import { useEffect, type RefObject } from "react";

export const OF_CHROME_STYLE_ID = "oi-of-chrome";

export const OF_INSIGHTS_ATTR = "data-oi-insights";
export const OF_INSIGHTS_PX = 280;

export const OF_CHROME_CSS = `
.l-header{position:absolute!important;pointer-events:none!important}
.l-header>nav{opacity:0!important;visibility:hidden!important}
#content{border-right:none!important;max-width:100%!important}
#content:after{display:none!important}
.l-wrapper__content{margin-left:0!important;max-width:100%}
.container{max-width:100%!important;padding:0!important}
.l-wrapper__sidebar{flex:1 0 300px!important;min-width:300px!important;max-width:none!important;margin-right:0!important;padding-right:16px!important}
@media(min-width:1004px){.b-chats__conversations-list{max-width:345px!important;flex:0 0 345px!important}}
@media(max-width:1003.98px){.b-chats__conversations-list{flex:1 1 auto!important}.b-chats__conversations-content.m-empty-chat{display:none!important}}
.b-chats__conversations{max-width:100%!important}
html[${OF_INSIGHTS_ATTR}] .b-chats__conversations{padding-right:${OF_INSIGHTS_PX}px!important}
html[${OF_INSIGHTS_ATTR}] .b-chats__conversations-content{max-width:none!important}
#content>*{max-width:100%!important;margin-left:0!important}
.banner_place,.b-login-posts-wrapper,.l-footer-static,.b-login-posts-outer,.contact_button.visible-lg{display:none!important}
.b-make-post__actions{min-width:0!important;max-width:100%!important}
.b-make-post__actions__btns{flex:0 1 auto!important;min-width:0!important;overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
.b-make-post__actions .b-chat__btn-submit{flex:0 0 auto!important}
`;

export function injectOfChrome(doc: Document | null | undefined): boolean {
  if (!doc?.head) return false;
  if (doc.getElementById(OF_CHROME_STYLE_ID)) return true;
  const style = doc.createElement("style");
  style.id = OF_CHROME_STYLE_ID;
  style.textContent = OF_CHROME_CSS;
  doc.head.appendChild(style);
  return true;
}

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

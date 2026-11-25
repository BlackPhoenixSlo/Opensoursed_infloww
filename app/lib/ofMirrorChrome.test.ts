import { describe, expect, it } from "vitest";
import { OF_CHROME_CSS, OF_CHROME_STYLE_ID, injectOfChrome } from "./ofMirrorChrome";

describe("injectOfChrome", () => {
  it("adds Infloww's nav-hiding stylesheet to the page once", () => {
    document.head.innerHTML = "";
    expect(injectOfChrome(document)).toBe(true);
    expect(injectOfChrome(document)).toBe(true);
    const styles = document.head.querySelectorAll(`#${OF_CHROME_STYLE_ID}`);
    expect(styles).toHaveLength(1);
    expect(styles[0].textContent).toContain(".l-header>nav{opacity:0!important;visibility:hidden!important}");
    expect(styles[0].textContent).toContain(".l-wrapper__content{margin-left:0!important");
  });

  it("keeps the chat list's 345px column only from OF's 1004px two-pane width; below it the list fills, no empty pane", () => {
    const css = OF_CHROME_CSS.replace(/@media[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}/g, "");
    expect(css).not.toContain(".b-chats__conversations-list{");
    expect(OF_CHROME_CSS).toContain("@media(min-width:1004px){.b-chats__conversations-list{max-width:345px!important;flex:0 0 345px!important}}");
    expect(OF_CHROME_CSS).toContain("@media(max-width:1003.98px){.b-chats__conversations-list{flex:1 1 auto!important}.b-chats__conversations-content.m-empty-chat{display:none!important}}");
  });

  it("waits for a document with a head", () => {
    expect(injectOfChrome(null)).toBe(false);
  });
});

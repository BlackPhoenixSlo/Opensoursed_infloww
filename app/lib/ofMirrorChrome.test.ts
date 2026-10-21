import { describe, expect, it } from "vitest";
import { OF_CHROME_STYLE_ID, injectOfChrome } from "./ofMirrorChrome";

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

  it("waits for a document with a head", () => {
    expect(injectOfChrome(null)).toBe(false);
  });
});

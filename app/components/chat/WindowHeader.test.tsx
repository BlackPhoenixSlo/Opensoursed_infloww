/**
 * The Window header's Inflowwww mark (`goToDashboard`): Messages Pro's window has no sidebar, and in the desktop
 * app no address bar, so the mark is the way back to the Dashboard, in the window that opened this one if any;
 * otherwise its `next/link` goes there in this window.
 */
import type { MouseEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { goToDashboard } from "./WindowHeader";

const realOpener = window.opener;

function click(mods: Partial<Pick<MouseEvent, "button" | "metaKey" | "ctrlKey" | "shiftKey" | "altKey">> = {}) {
  const e = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...mods, preventDefault: vi.fn() };
  goToDashboard(e as unknown as MouseEvent<HTMLAnchorElement>);
  return e;
}

function stubOpener(opener: unknown) {
  Object.defineProperty(window, "opener", { configurable: true, value: opener });
}

afterEach(() => {
  stubOpener(realOpener);
});

describe("goToDashboard", () => {
  it("in the Messages Pro window, sends the window that opened it to the Dashboard and brings it to the front", () => {
    const main = { closed: false, location: { assign: vi.fn() }, focus: vi.fn() };
    stubOpener(main);
    const e = click();
    expect(e.preventDefault).toHaveBeenCalled();
    expect(main.location.assign).toHaveBeenCalledWith("/");
    expect(main.focus).toHaveBeenCalled();
  });

  it("with no opener, or a closed one, leaves the click to the link (the Dashboard in this window)", () => {
    stubOpener(null);
    expect(click().preventDefault).not.toHaveBeenCalled();

    const closed = { closed: true, location: { assign: vi.fn() }, focus: vi.fn() };
    stubOpener(closed);
    expect(click().preventDefault).not.toHaveBeenCalled();
    expect(closed.location.assign).not.toHaveBeenCalled();
  });

  it("a modified click keeps the browser's own behaviour, even with an opener", () => {
    const main = { closed: false, location: { assign: vi.fn() }, focus: vi.fn() };
    stubOpener(main);
    expect(click({ metaKey: true }).preventDefault).not.toHaveBeenCalled();
    expect(main.location.assign).not.toHaveBeenCalled();
  });
});

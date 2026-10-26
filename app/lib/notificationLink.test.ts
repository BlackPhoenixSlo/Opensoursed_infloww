import type { MouseEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fanTabOf, IN_PLACE_KEY, notificationHref, onNotificationClick, openNotification, setFanTabOpener } from "./notificationLink";

function ev(overrides: Partial<MouseEvent> = {}): MouseEvent {
  return {
    defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false,
    preventDefault: vi.fn(), ...overrides,
  } as unknown as MouseEvent;
}

afterEach(() => vi.restoreAllMocks());

describe("notificationHref", () => {
  it("links a known Fan's Deep link marked to open as a Fan tab, money with ?refresh=media", () => {
    expect(notificationHref("300", { id: 555, name: "Ann Lee" })).toBe("/messages-pro/300/555?fanTab=Ann+Lee");
    expect(notificationHref("300", { id: 555, username: "ann" }, { refresh: true }))
      .toBe("/messages-pro/300/555?refresh=media&fanTab=ann");
    expect(notificationHref("300", { id: 555 })).toBe("/messages-pro/300/555?fanTab=fan+555");
  });

  it("links a Fan known by username alone to its resolver, still marked, and nobody to nothing", () => {
    // The resolver keeps the query on its way to the id's Deep link.
    expect(notificationHref("300", { username: "ann b" })).toBe("/messages-pro/300/u/ann%20b?fanTab=ann+b");
    expect(notificationHref("300", { username: "ann", name: "Ann" }, { refresh: true }))
      .toBe("/messages-pro/300/u/ann?refresh=media&fanTab=Ann");
    expect(notificationHref("300", {})).toBeNull();
  });

  it("round-trips through fanTabOf, a Fansly snowflake kept exact", () => {
    expect(fanTabOf(notificationHref("a b", { id: "900604711209099264", name: "Zoë" })!))
      .toEqual({ accountId: "a b", fanId: "900604711209099264", name: "Zoë" });
    expect(fanTabOf("/messages-pro/300/555?refresh=media")).toBeNull();
    expect(fanTabOf("/messages-pro/300/u/ann?fanTab=ann")).toBeNull();
  });
});

describe("openNotification", () => {
  it("inside Messages Pro opens the Fan tab in place, passing a money link's refresh: no window.open", () => {
    const open = vi.spyOn(window, "open");
    const inPage = vi.fn();
    const off = setFanTabOpener(inPage);
    openNotification("/messages-pro/300/555?refresh=media&fanTab=Ann");
    openNotification("/messages-pro/300/556?fanTab=Bo");
    off();
    expect(inPage.mock.calls).toEqual([
      [{ accountId: "300", fanId: 555, name: "Ann" }, { refresh: true }],
      [{ accountId: "300", fanId: 556, name: "Bo" }, { refresh: false }],
    ]);
    expect(open).not.toHaveBeenCalled();
  });

  it("anywhere else opens the link in the Messages Pro window", () => {
    const location = { pathname: "/messages-pro", search: "", href: "" };
    const focus = vi.fn();
    const open = vi.spyOn(window, "open").mockReturnValue({ location, focus } as unknown as Window);
    const stale = vi.fn();
    setFanTabOpener(stale)(); // unregistered: the page unmounted
    openNotification("/messages-pro/300/555?fanTab=Ann");
    expect(open).toHaveBeenCalledWith("", "messages-pro", "popup,width=1470,height=915");
    expect(location.href).toBe("/messages-pro/300/555?fanTab=Ann");
    expect(focus).toHaveBeenCalled();
    expect(stale).not.toHaveBeenCalled();
  });

  it("from another window hands the Fan to a Messages Pro page that is up: in place, focused, no navigation", () => {
    const location = { pathname: "/messages-pro", search: "", href: "" };
    const focus = vi.fn();
    const takes = vi.fn(() => true);
    vi.spyOn(window, "open").mockReturnValue({ location, focus, [IN_PLACE_KEY]: takes } as unknown as Window);
    openNotification("/messages-pro/300/555?refresh=media&fanTab=Ann");
    expect(takes).toHaveBeenCalledWith("/messages-pro/300/555?refresh=media&fanTab=Ann");
    expect(focus).toHaveBeenCalled();
    expect(location.href).toBe("");
    expect(window.open).toHaveBeenCalledTimes(1);
  });

  it("a username link inside Messages Pro opens through the window: only its resolver knows the Fan id", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    const inPage = vi.fn();
    const off = setFanTabOpener(inPage);
    openNotification("/messages-pro/300/u/ann?fanTab=ann");
    off();
    expect(inPage).not.toHaveBeenCalled();
    expect(window.open).toHaveBeenLastCalledWith("/messages-pro/300/u/ann?fanTab=ann", "messages-pro", "popup,width=1470,height=915");
  });
});

describe("onNotificationClick", () => {
  it("a plain left click is handled; modified clicks keep the browser's link behaviour", () => {
    const inPage = vi.fn();
    const off = setFanTabOpener(inPage);
    const plain = ev();
    onNotificationClick(plain, "/messages-pro/300/555?fanTab=Ann");
    expect(plain.preventDefault).toHaveBeenCalled();
    for (const mod of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      const e = ev(mod);
      onNotificationClick(e, "/messages-pro/300/555?fanTab=Ann");
      expect(e.preventDefault).not.toHaveBeenCalled();
    }
    off();
    expect(inPage).toHaveBeenCalledTimes(1);
  });
});

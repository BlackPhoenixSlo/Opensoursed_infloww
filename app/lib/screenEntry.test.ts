import { afterEach, describe, expect, it } from "vitest";

import { bootScreen, cookieValue, rememberScope } from "./screenEntry";
import type { Screen } from "./screenKey";

/** The cookies' decoded values (the Next jar's, `cookieValue`'s): an old saved Dashboard entry, the scope bit. */
const jar = (c: { entry?: string; scope?: string } = {}) => (n: string) => ({
  chatterly_entry: c.entry,
  chatterly_scope: c.scope,
})[n];
/** A Dashboard entry cookie as the Dashboard saved it before #374 (Per-model cards drawn). */
const STALE_ENTRY = JSON.stringify({ tz: "Asia/Tokyo", weekStart: "sunday", grid: true });

describe("bootScreen: which screen a route opens", () => {
  it.each<[string, string, Screen | null]>([
    ["Messages Pro: the inbox bundle's first page", "/messages-pro", { kind: "inbox", cursor: 0 }],
    ["another page: none", "/creators", null],
    ["a Messages Pro sub-route: none", "/messages-pro/x", null],
  ])("%s", (_n, path, want) => {
    expect(bootScreen(path, jar({ entry: STALE_ENTRY }))).toEqual(want);
  });

  // The Dashboard draws no card that reads its bundle: a guess would prefetch per-Creator OnlyFans reads for nothing.
  it.each<[string, Parameters<typeof jar>[0]]>([
    ["no cookie", {}],
    ["a stale grid:true entry", { entry: STALE_ENTRY }],
    ["a junk entry", { entry: "{oops" }],
  ])("Dashboard, %s: no bundle", (_n, c) => {
    expect(bootScreen("/", jar(c))).toBeNull();
    expect(bootScreen("/?window=month", jar(c))).toBeNull();
  });
});

describe("bootScreen: the one guess, from the cookies", () => {
  it("Messages Pro needs no cookie; another page: none", () => {
    expect(bootScreen("/messages-pro", jar())).toEqual({ kind: "inbox", cursor: 0 });
    expect(bootScreen("/messages-pro", jar({ scope: "all" }))).toEqual({ kind: "inbox", cursor: 0 });
    expect(bootScreen("/creators", jar({ entry: STALE_ENTRY }))).toBeNull();
  });

  it("Messages Pro with one Creator saved in scope: no inbox bundle (the page opens none)", () => {
    expect(bootScreen("/messages-pro", jar({ scope: "model" }))).toBeNull();
  });
});

describe("the cookies as the browser writes and AuthGate reads them (cookieValue: decoded, as Next's jar)", () => {
  afterEach(() => {
    for (const n of ["chatterly_entry", "chatterly_scope", "chatterly_x"]) document.cookie = `${n}=; path=/; max-age=0`;
  });
  const read = (n: string) => cookieValue(document.cookie, n);

  it("an old saved Dashboard entry is read harmlessly: no Dashboard bundle", () => {
    document.cookie = `chatterly_entry=${encodeURIComponent(STALE_ENTRY)}; path=/`;
    expect(read("chatterly_entry")).toBe(STALE_ENTRY);
    expect(bootScreen("/", read)).toBeNull();
  });

  it("the scope is one bit: model or all", () => {
    rememberScope(true);
    expect(read("chatterly_scope")).toBe("model");
    expect(bootScreen("/messages-pro", read)).toBeNull();
    rememberScope(false);
    expect(read("chatterly_scope")).toBe("all");
    expect(bootScreen("/messages-pro", read)).toEqual({ kind: "inbox", cursor: 0 });
  });

  it("an undecodable value: none (as Next's jar drops it)", () => {
    document.cookie = "chatterly_x=%E0%A4%A; path=/";
    expect(read("chatterly_x")).toBeUndefined();
  });
});

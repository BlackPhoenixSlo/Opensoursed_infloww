import { describe, expect, it } from "vitest";

import { isOlderVersion, LATEST_DESKTOP_VERSION } from "./desktopVersion";

describe("isOlderVersion", () => {
  it("compares major, minor and patch as numbers", () => {
    expect(isOlderVersion("0.2.0", "0.2.1")).toBe(true);
    expect(isOlderVersion("0.1.9", "0.2.1")).toBe(true);
    expect(isOlderVersion("0.2.9", "0.10.0")).toBe(true);
    expect(isOlderVersion("0.2.1", "0.2.1")).toBe(false);
    expect(isOlderVersion("0.3.0", "0.2.1")).toBe(false);
    expect(isOlderVersion("1.0.0", "0.9.9")).toBe(false);
  });

  it("reads a leading v and ignores a prerelease tag", () => {
    expect(isOlderVersion("v0.2.0", "0.2.1")).toBe(true);
    expect(isOlderVersion("0.2.1-beta.1", "0.2.1")).toBe(false);
  });

  it("never calls an unreadable version older", () => {
    expect(isOlderVersion("unknown", LATEST_DESKTOP_VERSION)).toBe(false);
    expect(isOlderVersion(undefined, LATEST_DESKTOP_VERSION)).toBe(false);
    expect(isOlderVersion("", LATEST_DESKTOP_VERSION)).toBe(false);
  });
});

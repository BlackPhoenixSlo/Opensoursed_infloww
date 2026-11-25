import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearAuthSnapshot, readAuthSnapshot, writeAuthSnapshot } from "./authSnapshot";

import type { AuthedUserDTO } from "@/contexts/UserContext";

const USER: AuthedUserDTO = { user_id: "u-1", username: "ann" };
const KEY = "chatterly:auth-snapshot:v1";

describe("authSnapshot", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("round-trips a confirmed principal", () => {
    writeAuthSnapshot(USER);
    expect(readAuthSnapshot()).toEqual(USER);
  });

  it("lives under the chatterly: namespace the identity wipe sweeps", () => {
    writeAuthSnapshot(USER);
    const keys = Object.keys(window.localStorage);
    expect(keys).toContain(KEY);
    expect(keys.every((k) => k.startsWith("chatterly:"))).toBe(true);
  });

  it("clears rather than stores when the principal is null", () => {
    writeAuthSnapshot(USER);
    writeAuthSnapshot(null);
    expect(readAuthSnapshot()).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("refuses to persist an impersonation overlay", () => {
    writeAuthSnapshot({
      ...USER,
      impersonating: { real_user_id: "founder", real_username: "root" },
    });
    expect(readAuthSnapshot()).toBeNull();
  });

  it("ignores an overlay that somehow reached storage", () => {
    window.localStorage.setItem(KEY, JSON.stringify({
      at: Date.now(),
      user: { ...USER, impersonating: { real_user_id: "f", real_username: "r" } },
    }));
    expect(readAuthSnapshot()).toBeNull();
  });

  it("expires after the TTL instead of painting a stale principal", () => {
    const fourDaysAgo = Date.now() - 4 * 24 * 60 * 60 * 1000;
    window.localStorage.setItem(KEY, JSON.stringify({ at: fourDaysAgo, user: USER }));
    expect(readAuthSnapshot()).toBeNull();
  });

  it("keeps a snapshot that is still inside the TTL", () => {
    const yesterday = Date.now() - 24 * 60 * 60 * 1000;
    window.localStorage.setItem(KEY, JSON.stringify({ at: yesterday, user: USER }));
    expect(readAuthSnapshot()).toEqual(USER);
  });

  it("treats malformed, unparseable, or user_id-less payloads as absent", () => {
    for (const raw of [
      "not json",
      JSON.stringify({ user: USER }),
      JSON.stringify({ at: Date.now() }),
      JSON.stringify({ at: Date.now(), user: { username: "ann" } }),
      JSON.stringify({ at: "recently", user: USER }),
    ]) {
      window.localStorage.setItem(KEY, raw);
      expect(readAuthSnapshot()).toBeNull();
    }
  });

  it("clearAuthSnapshot is safe to call when nothing is stored", () => {
    expect(() => clearAuthSnapshot()).not.toThrow();
    expect(readAuthSnapshot()).toBeNull();
  });
});

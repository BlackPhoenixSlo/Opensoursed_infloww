/**
 * lib/format — `fmtDuration`, the one that used to be three.
 *
 * VaultPicker's `fmtDur`, VaultTile's `fmtDuration` and a fourth copy written
 * for the composer's overlong-video warning were byte-identical apart from
 * their empty case (`""` vs `null`). Collapsing them onto `""` is only safe
 * because every consumer treats the empty value as falsy — VaultTile's
 * `{dur || "▶"}` is the one that would have regressed silently under `??`, so
 * the empty-string contract is pinned here rather than left implied.
 */
import { describe, expect, it } from "vitest";

import { fmtAgo, fmtDuration, parseUtc } from "./format";

describe("fmtDuration", () => {
  it("renders m:ss", () => {
    expect(fmtDuration(599)).toBe("9:59");
    expect(fmtDuration(300)).toBe("5:00");
    expect(fmtDuration(25)).toBe("0:25");
  });

  it("renders h:mm:ss from an hour up", () => {
    expect(fmtDuration(3600)).toBe("1:00:00");
    expect(fmtDuration(3725)).toBe("1:02:05");
    expect(fmtDuration(3599)).toBe("59:59");
  });

  it("floors fractional seconds rather than rounding into the next minute", () => {
    expect(fmtDuration(59.9)).toBe("0:59");
  });

  it("returns a FALSY empty string for absent/zero, so callers can fall back", () => {
    // `{dur || "▶"}` in VaultTile depends on this exactly.
    expect(fmtDuration(0)).toBe("");
    expect(fmtDuration(-5)).toBe("");
    expect(fmtDuration(null)).toBe("");
    expect(fmtDuration(undefined)).toBe("");
  });
});

describe("fmtAgo", () => {
  const at = (secsAgo: number) => new Date(Date.now() - secsAgo * 1000).toISOString();

  it("coarsens as it gets older", () => {
    expect(fmtAgo(at(12))).toBe("12s ago");
    expect(fmtAgo(at(5 * 60))).toBe("5 min ago");
    expect(fmtAgo(at(3 * 3600))).toBe("3 h ago");
    expect(fmtAgo(at(2 * 86400))).toBe("2 d ago");
  });

  it("returns null (render nothing) for absent or unparseable stamps", () => {
    expect(fmtAgo(null)).toBeNull();
    expect(fmtAgo(undefined)).toBeNull();
    expect(fmtAgo("not a date")).toBeNull();
  });

  it("reads a future stamp as 'soon' rather than negative time", () => {
    expect(fmtAgo(at(-120))).toBe("soon");
  });
});

describe("parseUtc", () => {
  it("reads a zone-less relay stamp as UTC, keeps a zoned stamp and a date alone, and refuses junk", () => {
    expect(parseUtc("2026-10-19T23:30:00")?.toISOString()).toBe("2026-10-19T23:30:00.000Z");
    expect(parseUtc("2026-10-19 23:30:00.123456")?.toISOString()).toBe("2026-10-19T23:30:00.123Z");
    expect(parseUtc("2026-10-19T23:30:00+02:00")?.toISOString()).toBe("2026-10-19T21:30:00.000Z");
    expect(parseUtc("2026-10-19T23:30:00Z")?.toISOString()).toBe("2026-10-19T23:30:00.000Z");
    expect(parseUtc("2026-10-19")?.toISOString()).toBe("2026-10-19T00:00:00.000Z");
    expect(parseUtc("nope")).toBeNull();
    expect(parseUtc(null)).toBeNull();
  });
});

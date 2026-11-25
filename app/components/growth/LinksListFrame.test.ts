import { afterEach, describe, expect, it, vi } from "vitest";

import { dateOnly } from "./LinksListFrame";

afterEach(() => vi.unstubAllEnvs());

describe("dateOnly", () => {
  it("read a naive stamp as UTC in a New York browser", () => {
    vi.stubEnv("TZ", "America/New_York");
    expect(dateOnly("2026-10-19T23:30:00", "UTC"))
      .toBe(new Date("2026-10-19T12:00:00Z").toLocaleDateString(undefined, { timeZone: "UTC" }));
    expect(dateOnly(null, "UTC")).toBe("—");
  });
});

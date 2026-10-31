/**
 * LinksListFrame's date helpers: our links' `created_at` comes zone-less (`datetime.utcnow().isoformat()`), so it is
 * read as UTC, not the browser's zone, before it is cut to the report time zone's day.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { dateOnly } from "./LinksListFrame";

afterEach(() => vi.unstubAllEnvs());

describe("dateOnly", () => {
  it("read a naive stamp as UTC in a New York browser", () => {
    vi.stubEnv("TZ", "America/New_York");
    // 23:30 UTC on 19 Oct; read as New York time it would be 03:30 UTC on the 20th. (createdDay: frameDates.test.ts.)
    expect(dateOnly("2026-10-19T23:30:00", "UTC"))
      .toBe(new Date("2026-10-19T12:00:00Z").toLocaleDateString(undefined, { timeZone: "UTC" }));
    expect(dateOnly(null, "UTC")).toBe("—");
  });
});

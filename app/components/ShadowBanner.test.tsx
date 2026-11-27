import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { copyAge, ShadowBanner } from "@/components/ShadowBanner";

afterEach(cleanup);

const AT = "2026-11-26T10:00:00Z";
const T = Date.parse(AT);

describe("copyAge", () => {
  it.each([
    [T + 20_000, "under a minute old"],
    [T + 12 * 60_000, "12 min old"],
    [T + 119 * 60_000, "119 min old"],
    [T + 3 * 3600_000, "3 h old"],
    [T + 72 * 3600_000, "3 days old"],
    [T - 60_000, "under a minute old"],
  ])("at %s → %s", (now, want) => {
    expect(copyAge(AT, now)).toBe(want);
  });

  it("unparseable stamp → null", () => {
    expect(copyAge("not a date", T)).toBeNull();
  });
});

describe("ShadowBanner", () => {
  it("names the shadow, read-only, and the copy's clock time", () => {
    render(<ShadowBanner copiedAt={AT} />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Shadow, read-only");
    expect(banner).toHaveTextContent("copy from 10:00 UTC");
  });

  it("an unreadable stamp still shows the banner", () => {
    render(<ShadowBanner copiedAt="x" />);
    expect(screen.getByRole("status")).toHaveTextContent("copy age unknown");
  });
});

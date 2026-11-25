import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { stillUrl } from "./ofMedia";
import type { OFMedia } from "@/lib/relay";

interface FixtureCase {
  name: string;
  media: Record<string, unknown>;
  still: string | null;
}
// Cases live in service/tests/fixtures/of_media_shapes.json, shared with the python suite: whichever side drifts goes red.
const fixture = JSON.parse(
  readFileSync(
    join(__dirname, "..", "..", "service", "tests", "fixtures", "of_media_shapes.json"),
    "utf8",
  ),
) as { sig: string; cases: FixtureCase[] };

function withSig<T>(value: T): T {
  return JSON.parse(
    JSON.stringify(value)
      .replace(/\.jpg/g, `.jpg${fixture.sig}`)
      .replace(/\.mp4/g, `.mp4${fixture.sig}`)
      .replace(/\.mp3/g, `.mp3${fixture.sig}`),
  ) as T;
}

describe("stillUrl — shared fixture with of_shapes.still_url", () => {
  it("has cases to check", () => {
    expect(fixture.cases.length).toBeGreaterThan(10);
  });

  for (const c of fixture.cases) {
    it(c.name, () => {
      const media = withSig(c.media) as unknown as OFMedia;
      const expected = c.still === null ? null : `${c.still}${fixture.sig}`;
      expect(stillUrl(media)).toBe(expected);
    });
  }
});

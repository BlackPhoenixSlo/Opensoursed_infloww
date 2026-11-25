import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { boolKnob } from "./boolKnob";

interface FixtureCase {
  name: string;
  absent?: boolean;
  value?: unknown;
  default: boolean;
  expect: boolean;
}
const fixture = JSON.parse(
  readFileSync(
    join(__dirname, "..", "..", "service", "tests", "fixtures", "bool_knob_cases.json"),
    "utf8",
  ),
) as { note: string; contract: string; cases: FixtureCase[] };

describe("boolKnob — the one catalogued-bool reader, shared table", () => {
  it("has cases to check", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(14);
  });

  for (const c of fixture.cases) {
    it(c.name, () => {
      const v = c.absent ? undefined : c.value;
      expect(boolKnob(v, c.default)).toBe(c.expect);
    });
  }

    // validate_payload skips None, so null reaches storage; reading it false on follow_back_gate/money_gate buys subscriptions
  it("gives a STORED null the declared default, not false", () => {
    expect(boolKnob(null, true)).toBe(true);
    expect(boolKnob(null, false)).toBe(false);
  });
});

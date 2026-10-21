/**
 * lib/boolKnob — the browser half of the one catalogued-bool contract.
 *
 * The truth table is NOT written here: it comes from
 * `service/tests/fixtures/bool_knob_cases.json`, the same table
 * `test_automation_rules_api.case_bool_knob_matches_the_typescript_half`
 * asserts `_common.bool_knob` against. Two implementations of one rule cannot
 * share code across the wire, so they share the fixture — add a row there and
 * whichever side drifts goes red. They HAD drifted (`[]` and `{}` read ON here
 * and OFF in the relay) and only a grep would have caught it.
 *
 * Read at runtime rather than imported so the fixture stays where python's test
 * data lives, outside the Next tsconfig's rootDir.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { boolKnob } from "./boolKnob";

interface FixtureCase {
  name: string;
  /** `true` when the key is absent altogether; otherwise `value` is present. */
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
      // An ABSENT key reads `undefined` off the payload; a stored one reads its
      // value. Both go through the same call, because the whole point of the
      // helper is that those two answer alike.
      const v = c.absent ? undefined : c.value;
      expect(boolKnob(v, c.default)).toBe(c.expect);
    });
  }

  // THE defect this file exists for, spelled out once outside the table so it
  // survives an accidental fixture edit: `_validate_payload_for_kind` skips
  // None rather than rejecting it, so `null` is the one non-boolean that reaches
  // storage — and on `follow_back_gate` / `money_gate` reading it as `false`
  // buys a subscription to every priced creator in the pool.
  it("gives a STORED null the declared default, not false", () => {
    expect(boolKnob(null, true)).toBe(true);
    expect(boolKnob(null, false)).toBe(false);
  });
});

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { holdsLogin, loginCount, MAX_LOGINS } from "./loginPaste";

interface FixtureCase {
  text: string;
  count: number;
  bad: [number, string][];
  holds: boolean;
}
const fixture = JSON.parse(
  readFileSync(join(__dirname, "..", "..", "service", "tests", "fixtures", "login_paste_cases.json"), "utf8"),
) as { note: string; cases: FixtureCase[] };

describe("loginPaste — shared table with service/login_paste.py", () => {
  it("has cases to check, the cap among them", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(40);
    expect(fixture.cases.some((c) => c.count === MAX_LOGINS && c.bad.length > 0)).toBe(true);
  });

  for (const c of fixture.cases) {
    it(`${JSON.stringify(c.text).slice(0, 80)} → ${c.count} / ${c.holds}`, () => {
      expect(loginCount(c.text)).toBe(c.count);
      expect(holdsLogin(c.text)).toBe(c.holds);
    });
  }
});

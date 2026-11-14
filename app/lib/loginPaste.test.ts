/**
 * lib/loginPaste — the browser half of the pasted-logins parser and credential guard. The table is NOT written
 * here: it is `service/tests/fixtures/login_paste_cases.json`, the one service/tests/test_login_paste.py asserts
 * service/login_paste.py against. Add a row there and whichever half drifts goes red. Read at runtime (the
 * fixture lives outside the Next tsconfig's rootDir), as boolKnob.test.ts does.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { holdsLogin, loginCount, MAX_LOGINS } from "./loginPaste";

interface FixtureCase {
  text: string;
  count: number;
  /** parse's bad lines: the relay's only. */
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

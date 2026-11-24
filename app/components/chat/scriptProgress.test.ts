import { describe, expect, it } from "vitest";

import { EMPTY_SCRIPT_PROGRESS, canSkip, epochOf, scriptProgress, type ScriptProgressAction } from "./scriptProgress";

const skip = (scriptId: string, now: number): ScriptProgressAction => ({ type: "skip", scriptId, now });
const end = (scriptId: string): ScriptProgressAction => ({ type: "end", scriptId });

describe("script progress", () => {
  it.each<[string, ScriptProgressAction[], ScriptProgressAction[], boolean]>([
    ["allows a send with no intervening action", [], [], true],
    ["blocks a pending send after Skip", [], [skip("promo", 0)], false],
    ["blocks a pending send after End", [], [end("promo")], false],
    ["allows a send started after End", [end("promo")], [], true],
    ["keeps other scripts independent", [], [end("other"), skip("other", 0)], true],
    ["ignores Skip during cooldown", [skip("promo", 0)], [skip("promo", 399)], true],
    ["accepts Skip when cooldown expires", [skip("promo", 0)], [skip("promo", 400)], false],
    ["does not extend cooldown on End", [skip("other", 0), end("other")], [skip("promo", 400)], false],
  ])("%s", (_name, before, during, settles) => {
    const started = before.reduce(scriptProgress, EMPTY_SCRIPT_PROGRESS);
    const token = epochOf(started, "promo");
    expect(epochOf(during.reduce(scriptProgress, started), "promo") === token).toBe(settles);
  });

  it.each<[string, ScriptProgressAction[], number, boolean]>([
    ["first Skip", [], 0, true],
    ["399 ms after a Skip", [skip("promo", 0)], 399, false],
    ["400 ms after a Skip", [skip("promo", 0)], 400, true],
    ["right after End", [end("promo")], 0, true],
  ])("canSkip: %s", (_name, before, now, allowed) => {
    expect(canSkip(before.reduce(scriptProgress, EMPTY_SCRIPT_PROGRESS), now)).toBe(allowed);
  });
});

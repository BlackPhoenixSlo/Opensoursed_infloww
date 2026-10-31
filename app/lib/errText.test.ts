import { describe, expect, it } from "vitest";

import { errText } from "./errText";

describe("errText", () => {
  it.each<[string, unknown, string | undefined, string]>([
    ["an Error's message", new Error("relay 500"), undefined, "relay 500"],
    ["an Error with no message", new Error(""), "save failed", "save failed"],
    ["a non-Error", "down", undefined, "down"],
    ["nothing, the default fallback", undefined, undefined, "failed"],
    ["nothing, a given fallback", null, "save failed", "save failed"],
  ])("%s", (_name, e, fallback, want) => {
    expect(errText(e, fallback)).toBe(want);
  });
});

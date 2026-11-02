import { describe, expect, it } from "vitest";

import { errText } from "./errText";

describe("errText", () => {
  it.each<[string, unknown, string | undefined, string]>([
    ["an Error's message", new Error("relay 500"), undefined, "relay 500"],
    ["an Error's message beats a given fallback", new Error("relay 500"), "save failed", "relay 500"],
    ["an Error with no message, a given fallback", new Error(""), "save failed", "save failed"],
    ["a non-Error", "down", undefined, "down"],
    ["nothing, the default fallback", undefined, undefined, "failed"],
    ["nothing, a given fallback", null, "save failed", "save failed"],
    ["an Error with no message, the default fallback", new Error(""), undefined, "failed"],
    ["null, the default fallback", null, undefined, "failed"],
    ["an object with a message is not an Error", { message: "nope" }, undefined, "[object Object]"],
    ["a thrown string beats the fallback", "down", "save failed", "down"],
  ])("%s", (_name, e, fallback, want) => {
    expect(errText(e, fallback)).toBe(want);
  });
});

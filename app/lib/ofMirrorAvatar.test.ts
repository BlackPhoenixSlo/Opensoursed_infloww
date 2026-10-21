import { describe, expect, it } from "vitest";
import { initials, textAvatar } from "./ofMirrorAvatar";

describe("OF's text avatar", () => {
  it("one word's first two (its first emoji out), else two words' first letters", () => {
    expect(["user929", "Paula 🥇 BEST", "summer ♡", "Marcus, 29, Austin", "🥇Gold", "Cliff", "a"].map(textAvatar)).toEqual(["Us", "P", "S", "M2", "Go", "Cl", "A"]);
  });

  it("initials: the display name over the name; a login-only name (u<id>) has none", () => {
    expect([{ id: 3, name: "u3" }, { id: 3, name: "u3", displayName: "Big Tipper" }, { id: 4, name: "Beta Two" }, { id: 5 }].map(initials)).toEqual(["", "BT", "BT", ""]);
  });
});

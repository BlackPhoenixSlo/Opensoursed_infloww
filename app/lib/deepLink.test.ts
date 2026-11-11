import { describe, expect, it } from "vitest";

import { pick, stepLabel, stepsOf, withSteps, type Candidate } from "./deepLink";

describe("withSteps / stepsOf", () => {
  it.each([
    ["/growth/smart-messages?tab=mass", ["OF mass messages"], "/growth/smart-messages?tab=mass#go=OF+mass+messages"],
    ["/messages-pro", ["+", "Mass message"], "/messages-pro#go=Mass+message"],
    ["/creators", [], "/creators"],
    ["/creators", ["  ", "+"], "/creators"],
  ])("%s + %j → %s", (href, steps, want) => {
    expect(withSteps(href, steps)).toBe(want);
  });

  it("round-trips, and ignores any other hash", () => {
    const h = withSteps("/x", ["OF mass messages", "the Auto-unsend card"]);
    expect(stepsOf(h.slice(h.indexOf("#")))).toEqual(["OF mass messages", "the Auto-unsend card"]);
    expect(stepsOf("#top")).toEqual([]);
    expect(stepsOf("")).toEqual([]);
  });
});

describe("stepLabel", () => {
  it.each([
    ["the Auto-unsend card", "auto-unsend"],
    ["**OF mass messages**", "of mass messages"],
    ["Auto-unsend (automation)", "auto-unsend automation"],
    ["the Model block", "model"],
    ["+", ""],
  ])("%s → %s", (raw, want) => expect(stepLabel(raw)).toBe(want));
});

describe("pick", () => {
  const page: Candidate[] = [
    { text: "Priority mass messages", kind: "tab" },
    { text: "OF mass messages", kind: "tab" },
    { text: "Auto-unsend (automation)", kind: "heading" },
    { text: "OF mass messages", kind: "heading" },
    { text: "Advanced", kind: "toggle" },
  ];
  it.each([
    ["OF mass messages", 1], // exact, the tab over the same-named heading
    ["the Auto-unsend card", 2], // prefix of the heading's text
    ["mass messages", -1], // a suffix is not a match
    ["Advanced settings", -1],
    ["the Advanced section", 4],
    ["+", -1],
  ])("%s → %i", (step, want) => expect(pick(page, step)).toBe(want));
});

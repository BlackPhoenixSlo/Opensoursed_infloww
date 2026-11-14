import { describe, expect, it } from "vitest";

import { APPLIED_LINE, STALE_LINE, applyBody, diffLine, resultLine, slotsFrom, type ConfigStatus } from "./fullAiConfigEdit";

const GOOD = {
  rev: 4,
  before: { reply_speed: "0-2m", gifs: true },
  after: { reply_speed: "0-15-60", gifs: true },
  diffs: [{ field: "reply_speed", label: "Reply speed", before: "0-2m", after: "0-15-60" }],
  account_name: "Model A",
};

describe("slotsFrom", () => {
  it("reads good slots", () => {
    expect(slotsFrom(GOOD)).toEqual(GOOD);
  });

  it.each([
    ["missing rev", { ...GOOD, rev: undefined }],
    ["rev not an integer", { ...GOOD, rev: "4" }],
    ["after missing", { ...GOOD, after: null }],
    ["after an array", { ...GOOD, after: [] }],
    ["junk", "junk"],
    ["null", null],
  ])("%s → null", (_name, raw) => {
    expect(slotsFrom(raw)).toBeNull();
  });

  it("drops junk diffs and fills defaults", () => {
    expect(slotsFrom({ rev: 0, after: { gifs: false }, diffs: [null, { label: "x" }, { field: "gifs", before: true, after: false }] }))
      .toEqual({ rev: 0, before: {}, after: { gifs: false }, account_name: "",
        diffs: [{ field: "gifs", label: "gifs", before: true, after: false }] });
  });
});

describe("applyBody / resultLine / diffLine", () => {
  it("applyBody is the whole after on the proposal's rev", () => {
    expect(applyBody(slotsFrom(GOOD)!, "acc1")).toEqual({ account_id: "acc1", draft: GOOD.after, rev: 4 });
  });

  it.each<[ConfigStatus, unknown, string]>([
    [200, { rev: 5 }, APPLIED_LINE],
    [409, { detail: "x", rev: 6 }, STALE_LINE],
    [422, { errors: ["writer_timeout_s: must be 5..60", "gifs: must be true or false"] },
      "Not applied: writer_timeout_s: must be 5..60; gifs: must be true or false"],
    [422, null, "Not applied: the server refused the change."],
  ])("resultLine(%i)", (status, body, line) => {
    expect(resultLine(status, body)).toBe(line);
  });

  it("diffLine reads the value in plain words", () => {
    expect(diffLine(GOOD.diffs[0])).toBe("Reply speed: 0-2m → 0-15-60");
    expect(diffLine({ field: "gifs", label: "GIFs", before: true, after: false })).toBe("GIFs: on → off");
    expect(diffLine({ field: "writers", label: "Writers (in order)", before: ["a"], after: ["b", "c"] }))
      .toBe("Writers (in order): a → b, c");
  });
});

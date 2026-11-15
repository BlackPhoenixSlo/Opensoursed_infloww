import { describe, expect, it } from "vitest";

import { type FullAiConfig } from "./fullAiConfig";
import { keyRows, photoKeyMissing, readsPhotos } from "./fullAiKeys";

const PROV = { "euryale-v2.3": "nanogpt", "glm-5.3-flash": "zai", "euryale-v2.3-deepinfra": "deepinfra" };
const W = (writers: string[], photos?: boolean): FullAiConfig =>
  photos === undefined ? { writers } : { writers, describe_fan_photos: photos };

describe("keyRows (LLM keys row)", () => {
  it.each<[string, (FullAiConfig | null)[], string[]]>([
    ["photos default on: DeepInfra last", [W(["euryale-v2.3"]), W(["glm-5.3-flash"])], ["nanogpt", "zai", "deepinfra"]],
    ["off both sides: Writers only", [W(["euryale-v2.3"], false), W(["glm-5.3-flash"], false)], ["nanogpt", "zai"]],
    ["on in the draft only", [W(["euryale-v2.3"], true), W(["euryale-v2.3"], false)], ["nanogpt", "deepinfra"]],
    ["on in the checkpoint only", [W(["euryale-v2.3"], false), W(["euryale-v2.3"], true)], ["nanogpt", "deepinfra"]],
    ["a DeepInfra Writer: once", [W(["euryale-v2.3-deepinfra", "euryale-v2.3"]), null], ["deepinfra", "nanogpt"]],
    ["unloaded sides: nothing", [null, null], []],
  ])("%s", (_, sides, ids) => {
    expect(keyRows(sides, PROV, undefined)?.map((r) => r.id)).toEqual(ids);
  });

  it("null until writer_providers answers; labels", () => {
    expect(keyRows([W(["euryale-v2.3"])], undefined, undefined)).toBeNull();
    expect(keyRows([W([])], PROV, { deepinfra: "DeepInfra" })).toEqual([{ id: "deepinfra", label: "DeepInfra" }]);
  });
});

describe("readsPhotos / photoKeyMissing", () => {
  const SET = { deepinfra: { set: true } };
  const UNSET = { deepinfra: { set: false } };
  it.each<[string, (FullAiConfig | null)[], Record<string, { set: boolean }> | undefined, boolean, boolean]>([
    ["on, no key", [W([]), W([])], UNSET, true, true],
    ["on, provider absent from the read", [W([]), null], {}, true, true],
    ["on, key set", [W([]), W([])], SET, true, false],
    ["off both, no key", [W([], false), W([], false)], UNSET, false, false],
    ["on, keys not read yet", [W([], true), null], undefined, true, false],
    ["unloaded", [null, null], UNSET, false, false],
  ])("%s", (_, sides, providers, reads, missing) => {
    expect(readsPhotos(sides)).toBe(reads);
    expect(photoKeyMissing(sides, providers)).toBe(missing);
  });
});

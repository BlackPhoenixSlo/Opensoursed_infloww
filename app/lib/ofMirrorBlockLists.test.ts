import { describe, expect, it } from "vitest";
import {
  badIps,
  blockedOf,
  canCancelIps,
  canSubmitCountries,
  canSubmitIps,
  countriesOf,
  countryAsk,
  countryInit,
  countryName,
  countryPayload,
  countryReducer,
  filterCountries,
  ipAsk,
  ipInit,
  ipLines,
  ipPayload,
  ipReducer,
  ipText,
  isIpEntry,
  type CountryAction,
  type CountryState,
  type IpAction,
  type IpState,
} from "./ofMirrorBlockLists";

const LIST = [
  { code: "AQ", name: "Antarctica" },
  { code: "US", name: "United States of America" },
];

describe("reads", () => {
  it.each([
    [{ blockedCountries: ["AQ", 3], blockedStates: [7, "x", 1.5], blockedIps: ["192.0.2.1", null] }, { countries: ["AQ"], states: [7], ips: ["192.0.2.1"] }],
    [{}, { countries: [], states: [], ips: [] }],
    [null, null],
    ["x", null],
    [{ blockedCountries: "AQ" }, { countries: [], states: [], ips: [] }],
  ])("blockedOf(%j)", (read, want) => expect(blockedOf(read)).toEqual(want));

  it.each([
    [[...LIST, { code: 1, name: "x" }, null, { code: "DE" }], LIST],
    [{ list: LIST }, []],
    [undefined, []],
  ])("countriesOf(%j)", (read, want) => expect(countriesOf(read)).toEqual(want));

  it.each([
    ["", 2],
    ["anta", 1],
    [" UNITED ", 1],
    ["zz", 0],
  ])("filterCountries(%j) keeps %i", (q, n) => expect(filterCountries(LIST, q)).toHaveLength(n));

  it("countryName falls back to the code", () => expect([countryName(LIST, "AQ"), countryName(LIST, "ZZ")]).toEqual(["Antarctica", "ZZ"]));
});

describe("countryReducer", () => {
  const s0 = countryInit({ countries: ["US"], states: [4] });
  const run = (s: CountryState, ...as: CountryAction[]) => as.reduce(countryReducer, s);
  it.each<[string, CountryAction[], Partial<CountryState>, boolean]>([
    ["starts saved, no Save", [], { picked: ["US"], initial: ["US"] }, false],
    ["a pick enables Save", [{ type: "toggle", code: "AQ" }], { picked: ["US", "AQ"] }, true],
    ["unpicking a saved one enables Save", [{ type: "toggle", code: "US" }], { picked: [] }, true],
    ["pick and unpick: no change", [{ type: "toggle", code: "AQ" }, { type: "toggle", code: "AQ" }], { picked: ["US"] }, false],
    ["save marks saving; no second Save", [{ type: "toggle", code: "AQ" }, { type: "save" }], { saving: true }, false],
    ["a toggle while saving is ignored", [{ type: "toggle", code: "AQ" }, { type: "save" }, { type: "toggle", code: "DE" }], { picked: ["US", "AQ"] }, false],
    ["saved: the picks are the saved list", [{ type: "toggle", code: "AQ" }, { type: "save" }, { type: "saved" }], { initial: ["US", "AQ"], saving: false }, false],
    ["failed: back to the saved list", [{ type: "toggle", code: "AQ" }, { type: "save" }, { type: "failed" }], { picked: ["US"], saving: false }, false],
    ["save with no change does nothing", [{ type: "save" }], { saving: false }, false],
    ["reset drops picks and search", [{ type: "toggle", code: "AQ" }, { type: "search", text: "x" }, { type: "reset" }], { picked: ["US"], search: "" }, false],
    ["load replaces an unchanged state", [{ type: "load", countries: ["DE"], states: [] }], { initial: ["DE"], picked: ["DE"], states: [] }, false],
    ["load keeps the typed search", [{ type: "search", text: "ant" }, { type: "load", countries: [], states: [] }], { search: "ant", picked: [] }, false],
    ["load keeps the operator's picks", [{ type: "toggle", code: "AQ" }, { type: "load", countries: ["DE"], states: [] }], { initial: ["US"], picked: ["US", "AQ"] }, true],
  ])("%s", (_n, as, want, can) => {
    const s = run(s0, ...as);
    expect(s).toMatchObject(want);
    expect(canSubmitCountries(s)).toBe(can);
  });

  const u0 = countryInit(null);
  it.each<[string, CountryAction[], Partial<CountryState>, boolean]>([
    ["unloaded: starts empty, no Save", [], { loaded: false, picked: [] }, false],
    ["unloaded: a toggle is ignored", [{ type: "toggle", code: "AQ" }], { loaded: false, picked: [] }, false],
    ["unloaded: search is ignored", [{ type: "search", text: "ant" }], { search: "" }, false],
    ["unloaded: save does nothing", [{ type: "toggle", code: "AQ" }, { type: "save" }], { saving: false }, false],
    ["load makes it editable", [{ type: "load", countries: ["US"], states: [4] }, { type: "toggle", code: "AQ" }], { loaded: true, picked: ["US", "AQ"], states: [4] }, true],
  ])("%s", (_n, as, want, can) => {
    const s = run(u0, ...as);
    expect(s).toMatchObject(want);
    expect(canSubmitCountries(s)).toBe(can);
  });

  it("after load the payload keeps the existing countries and states", () =>
    expect(countryPayload(run(u0, { type: "toggle", code: "AQ" }, { type: "load", countries: ["US"], states: [4] }, { type: "toggle", code: "AQ" }))).toEqual({
      blockedCountries: ["US", "AQ"],
      blockedStates: [4],
    }));

  it("countryPayload: the whole list, states as read", () =>
    expect(countryPayload(run(s0, { type: "toggle", code: "AQ" }))).toEqual({ blockedCountries: ["US", "AQ"], blockedStates: [4] }));

  it.each([
    [["Antarctica"], "People in Antarctica will not be able to see your profile or posts."],
    [[], "No country will be blocked."],
  ])("countryAsk(%j) names them", (names, text) => expect(countryAsk(names)).toEqual({ title: "Block by country?", text, ok: "Save" }));
});

describe("Block by IP", () => {
  it.each([
    ["192.0.2.1", true],
    ["192.0.2.0/24", true],
    ["192.0.*.1", true],
    ["0.0.0.0/32", true],
    ["192.0.2.0/33", false],
    ["192.0.*.0/24", false],
    ["256.0.0.1", false],
    ["192.0.2", false],
    ["192.0.2.1/24/1", false],
    ["2001:db8::1", true],
    ["2001:db8::/32", true],
    ["2001:db8::/129", false],
    ["2001:db8::g", false],
    ["hello", false],
    ["", false],
  ])("isIpEntry(%j) = %s", (e, ok) => expect(isIpEntry(e)).toBe(ok));

  it("lines are trimmed, blanks dropped; text joins with newlines", () => {
    expect(ipLines(" 192.0.2.1 \n\n 2001:db8::1\n")).toEqual(["192.0.2.1", "2001:db8::1"]);
    expect(badIps("192.0.2.1\nnope")).toEqual(["nope"]);
    expect(ipText(["a", "b"])).toBe("a\nb");
  });

  const s0 = ipInit(["198.51.100.7"]);
  const run = (s: IpState, ...as: IpAction[]) => as.reduce(ipReducer, s);
  it.each<[string, IpAction[], Partial<IpState>, boolean, boolean]>([
    ["starts saved", [], { text: "198.51.100.7" }, false, false],
    ["an added line enables both", [{ type: "edit", text: "198.51.100.7\n192.0.2.1" }], {}, true, true],
    ["a bad line: Cancel only", [{ type: "edit", text: "192.0.2.999" }], {}, false, true],
    ["whitespace only: no list change", [{ type: "edit", text: " 198.51.100.7 \n" }], {}, false, true],
    ["cancel puts the saved text back", [{ type: "edit", text: "192.0.2.1" }, { type: "cancel" }], { text: "198.51.100.7" }, false, false],
    ["emptied: Save sends []", [{ type: "edit", text: "" }], {}, true, true],
    ["saving: neither", [{ type: "edit", text: "192.0.2.1" }, { type: "save" }], { saving: true }, false, false],
    ["edit while saving is ignored", [{ type: "edit", text: "192.0.2.1" }, { type: "save" }, { type: "edit", text: "x" }], { text: "192.0.2.1" }, false, false],
    ["saved: the lines are the saved list", [{ type: "edit", text: " 192.0.2.1\n" }, { type: "save" }, { type: "saved" }], { saved: ["192.0.2.1"], text: "192.0.2.1", saving: false }, false, false],
    ["failed: back to the saved list", [{ type: "edit", text: "192.0.2.1" }, { type: "save" }, { type: "failed" }], { text: "198.51.100.7", saving: false }, false, false],
    ["load replaces an unedited field", [{ type: "load", ips: [] }], { saved: [], text: "" }, false, false],
    ["load keeps an edit", [{ type: "edit", text: "192.0.2.1" }, { type: "load", ips: [] }], { saved: ["198.51.100.7"], text: "192.0.2.1" }, true, true],
  ])("%s", (_n, as, want, save, cancel) => {
    const s = run(s0, ...as);
    expect(s).toMatchObject(want);
    expect([canSubmitIps(s), canCancelIps(s)]).toEqual([save, cancel]);
  });

  const u0 = ipInit(null);
  it.each<[string, IpAction[], Partial<IpState>, boolean, boolean]>([
    ["unloaded: empty, neither", [], { loaded: false, text: "" }, false, false],
    ["unloaded: an edit is ignored", [{ type: "edit", text: "192.0.2.1" }], { loaded: false, text: "" }, false, false],
    ["unloaded: save does nothing", [{ type: "edit", text: "192.0.2.1" }, { type: "save" }], { saving: false }, false, false],
    ["load makes it editable", [{ type: "load", ips: ["198.51.100.7"] }, { type: "edit", text: "198.51.100.7\n192.0.2.1" }], { loaded: true }, true, true],
  ])("%s", (_n, as, want, save, cancel) => {
    const s = run(u0, ...as);
    expect(s).toMatchObject(want);
    expect([canSubmitIps(s), canCancelIps(s)]).toEqual([save, cancel]);
  });

  it("after load the payload keeps the existing IPs", () =>
    expect(ipPayload(run(u0, { type: "edit", text: "192.0.2.1" }, { type: "load", ips: ["198.51.100.7"] }, { type: "edit", text: "198.51.100.7\n192.0.2.1" }))).toEqual({
      blockedIps: ["198.51.100.7", "192.0.2.1"],
    }));

  it.each([
    ["192.0.2.1\n", { blockedIps: ["192.0.2.1"] }],
    ["", { blockedIps: [] }],
  ])("ipPayload(%j)", (text, want) => expect(ipPayload({ saved: [], text, saving: false, loaded: true })).toEqual(want));

  it.each([
    [["192.0.2.1"], "Visitors from 192.0.2.1 will not be able to see your profile or posts."],
    [[], "No IP address will be blocked."],
  ])("ipAsk(%j) names them", (ips, text) => expect(ipAsk(ips)).toEqual({ title: "Block by IP?", text, ok: "Save" }));
});

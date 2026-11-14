import { describe, expect, it } from "vitest";

import {
  DOMAIN_EMPTY_MSG, INITIAL_DOMAIN, bioDomainReducer, buildDomainPayload, canSave, domainError, exampleOf,
  normalizeDomain, notYet, statusLabel, type Action, type BioDomainForm,
} from "@/components/growth/bio/bioDomainForm";

const run = (actions: Action[], from: BioDomainForm = INITIAL_DOMAIN) => actions.reduce(bioDomainReducer, from);
const ALONE = "Enter the domain alone, like alicex.com: no https://, no slash, no spaces.";

describe("normalizeDomain / exampleOf", () => {
  it.each([[" Shop.Example.COM ", "shop.example.com"], ["HTTPS://a.io/", "https://a.io/"]])(
    "%j → %j", (raw, want) => expect(normalizeDomain(raw)).toBe(want));
  it.each([["alice_x", "alicex.com"], ["___", "yourname.com"]])("%j → %j", (u, want) => expect(exampleOf(u)).toBe(want));
});

describe("domainError (v2's sentences)", () => {
  it.each([
    ["", DOMAIN_EMPTY_MSG], ["   ", DOMAIN_EMPTY_MSG], ["nodot", ALONE], ["1.2.3.4", ALONE], ["a_b.com", ALONE],
    ["-a.com", ALONE], ["a..b.com", ALONE], [`${"a".repeat(64)}.com`, ALONE], [`${`${"a".repeat(60)}.`.repeat(5)}com`, ALONE],
    ["https://a.com/", ALONE], ["a.com/", ALONE], ["a.com.", ALONE], ["a b.com", ALONE],
    ["ofl.ink", "ofl.ink is one of ofl.ink's own addresses. Use a domain you own."],
    ["x.ofl.ink", "x.ofl.ink is one of ofl.ink's own addresses. Use a domain you own."],
    ["App.Inflowwww.com", "app.inflowwww.com is one of ofl.ink's own addresses. Use a domain you own."],
    ["myofl.ink", null], [" Links.Example.com ", null], ["xn--bcher-kva.example", null],
  ])("%j → %j", (raw, want) => expect(domainError(raw, "alice_x")).toBe(want));
});

describe("bioDomainReducer", () => {
  it("submit with a refusal shows it and stays idle; an edit clears it", () => {
    const s = run([{ type: "set", draft: "nodot" }, { type: "submit", username: "alice_x" }]);
    expect(s).toMatchObject({ busy: null, error: ALONE });
    expect(canSave(s, "alice_x")).toBe(false);
    expect(run([{ type: "set", draft: "a.com" }], s).error).toBeNull();
  });

  it("a valid submit goes busy and blocks every other write; saved resets the form", () => {
    const s = run([{ type: "set", draft: " A.com " }, { type: "submit", username: "u" }]);
    expect(s.busy).toBe("save");
    expect(buildDomainPayload(s)).toEqual({ domain: "a.com" });
    expect(canSave(s, "u")).toBe(false);
    for (const a of [{ type: "submit", username: "u" }, { type: "start", op: "check" }, { type: "start", op: "remove" }] as Action[]) {
      expect(run([a], s)).toBe(s);
    }
    expect(run([{ type: "saved" }], s)).toEqual(INITIAL_DOMAIN);
  });

  it.each([
    ["check", { type: "checked", problems: ["No A record for a.com yet.", "Delete the AAAA record ::1."] } as Action,
      { busy: null }, "Not yet: No A record for a.com yet. Delete the AAAA record ::1."],
    ["check", { type: "checked", problems: [] } as Action, { busy: null, problems: [] }, null],
    ["remove", { type: "removed", domain: "a.com" } as Action, { ...INITIAL_DOMAIN, said: "a.com is removed." }, null],
    ["check", { type: "failed", msg: "Too many checks." } as Action, { busy: null, error: "Too many checks." }, null],
  ])("%s then %j", (op, end, want, line) => {
    const s = run([{ type: "start", op: op as "check" | "remove" }]);
    expect(s.busy).toBe(op);
    const after = run([end], s);
    expect(after).toMatchObject(want);
    expect(notYet(after)).toBe(line);
  });

  it("a new check clears the last failure; typing clears the removal line", () => {
    const failed = run([{ type: "start", op: "check" }, { type: "failed", msg: "x" }]);
    expect(run([{ type: "start", op: "check" }], failed).error).toBeNull();
    const removed = run([{ type: "start", op: "remove" }, { type: "removed", domain: "a.com" }]);
    expect(run([{ type: "set", draft: "b" }], removed).said).toBeNull();
  });

  it.each([["pending", "Waiting for DNS"], ["pending_cert", "Getting certificate"], ["live", "Live"], ["odd", "odd"]])(
    "statusLabel %s", (s, want) => expect(statusLabel(s)).toBe(want));
});

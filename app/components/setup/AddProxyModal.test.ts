/** AddProxyModal's draft helpers: the saved label and the first problem blocking Add proxy. */
import { describe, expect, it } from "vitest";

import { EMPTY_DRAFT, draftLabel, draftProblem, type DraftProblem, type ProxyDraft } from "./AddProxyModal";

const OK: ProxyDraft = { ...EMPTY_DRAFT, scheme: "http", host: "1.2.3.4", port: "8080" };
/** OK with an edited label, so clearing host or port does not trip the label check first. */
const NAMED: ProxyDraft = { ...OK, label: "x", labelEdited: true };

describe("draftLabel", () => {
  it.each<[ProxyDraft, string]>([
    // [draft, want]
    [EMPTY_DRAFT, ""],
    [OK, "1.2.3.4:8080"],
    [{ ...OK, host: "  1.2.3.4 " }, "1.2.3.4:8080"], // host trimmed
    [{ ...OK, host: "  " }, ""],
    [{ ...OK, port: "" }, ""],
    [{ ...OK, label: "typed", labelEdited: false }, "1.2.3.4:8080"], // typed label ignored until edited
    [{ ...OK, label: " mine ", labelEdited: true }, " mine "], // edited label as typed
    [{ ...OK, label: "", labelEdited: true }, ""],
  ])("%j -> %j", (d, want) => {
    expect(draftLabel(d)).toBe(want);
  });
});

describe("draftProblem", () => {
  const TAKEN = ["1.2.3.4:9090", "Proxy-A"];

  it.each<[ProxyDraft, string[] | null, DraftProblem | null]>([
    // [draft, takenLabels, want]: the kind decides where it shows (duplicate: under Proxy label)
    [OK, null, { kind: "notWired", text: "not wired: the proxy list has not loaded" }],
    [EMPTY_DRAFT, null, { kind: "notWired", text: "not wired: the proxy list has not loaded" }], // list check comes first
    [EMPTY_DRAFT, [], { kind: "invalid", text: "Fill in Proxy label" }],
    [{ ...OK, label: "  ", labelEdited: true }, [], { kind: "invalid", text: "Fill in Proxy label" }],
    [{ ...OK, scheme: "" }, [], { kind: "invalid", text: "Choose a Type" }],
    [{ ...NAMED, host: " " }, [], { kind: "invalid", text: "Fill in IP address" }],
    [{ ...NAMED, port: "" }, [], { kind: "invalid", text: "Port must be 1–65535" }],
    [{ ...OK, port: "0" }, [], { kind: "notWired", text: "not wired: port 0, as the Relay takes 1–65535" }],
    [{ ...OK, port: "00" }, [], { kind: "notWired", text: "not wired: port 0, as the Relay takes 1–65535" }],
    // defensive: the input strips non-digits, so the next three and "1e3" never reach here
    [{ ...OK, port: "abc" }, [], { kind: "invalid", text: "Port must be 1–65535" }],
    [{ ...OK, port: "-1" }, [], { kind: "invalid", text: "Port must be 1–65535" }],
    [{ ...OK, port: "1.5" }, [], { kind: "invalid", text: "Port must be 1–65535" }],
    [{ ...OK, port: "65536" }, [], { kind: "invalid", text: "Port must be 1–65535" }],
    [{ ...OK, port: "1" }, [], null],
    [{ ...OK, port: "65535" }, [], null],
    [{ ...OK, port: "1e3" }, [], null], // as coded: Number("1e3") = 1000
    [{ ...OK, port: "9090" }, TAKEN, { kind: "duplicate", text: 'A proxy named "1.2.3.4:9090" already exists' }],
    [{ ...OK, label: " Proxy-A ", labelEdited: true }, TAKEN, { kind: "duplicate", text: 'A proxy named "Proxy-A" already exists' }], // trimmed
    [{ ...OK, label: "proxy-a", labelEdited: true }, TAKEN, null], // case-sensitive
    [OK, TAKEN, null],
    [OK, [], null],
  ])("%j taken %j -> %j", (d, taken, want) => {
    expect(draftProblem(d, taken)).toEqual(want);
  });
});

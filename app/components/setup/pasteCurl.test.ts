import { describe, expect, it } from "vitest";

import {
  PASTE_PROXY, buildBootstrapBody, canSubmit, initialPasteCurl, pasteCurlReducer, submitError, validateCurl,
  type PasteCurlAction, type PasteCurlForm, type PasteCurlState,
} from "@/components/setup/pasteCurl";

const GOOD = "curl 'https://onlyfans.com/api2/v2/users/me' -H 'user-agent: Mozilla/5.0' -H 'x-bc: abc' -b 'auth_id=1; sess=s'";
const BLANK = { nickname: "", proxyLabel: "" };
const form = (over: Partial<PasteCurlForm> = {}): PasteCurlForm => ({ ...initialPasteCurl(BLANK), curl: GOOD, ...over });

describe("validateCurl", () => {
  // Only the `curl` prefix is checked here; cookies and headers are the relay's to parse (it says what is missing).
  it.each([
    ["a good curl", GOOD, null],
    ["surrounding whitespace", `\n  ${GOOD}  \n`, null],
    ["no cookie (-b)", "curl 'https://onlyfans.com/api2/v2/users/me' -H 'user-agent: UA'", null],
    ["no user-agent", "curl 'https://onlyfans.com/api2/v2/users/me' -b 'sess=s'", null],
    ["extra headers", `${GOOD} -H 'x-relay-static-param: sp' -H 'accept: */*' -H 'sec-fetch-mode: cors'`, null],
    ["Chrome's multi-line copy", "curl 'https://onlyfans.com/api2/v2/users/me' \\\n  -H 'user-agent: UA' \\\n  -b 'sess=s'", null],
    ["empty", "", "Must start with `curl ...`"],
    ["blank", "   ", "Must start with `curl ...`"],
    ["not a curl", "wget https://onlyfans.com", "Must start with `curl ...`"],
    ["a fetch() copy", "fetch(\"https://onlyfans.com/api2/v2/users/me\")", "Must start with `curl ...`"],
    ["case-sensitive", "CURL 'https://onlyfans.com'", "Must start with `curl ...`"],
  ])("%s", (_, text, err) => expect(validateCurl(text)).toBe(err));
});

describe("submitError", () => {
  it.each([
    ["good, no proxy", form(), null],
    ["good, a proxy label", form({ proxyLabel: "p1" }), null],
    ["paste proxy with a line", form({ proxyLabel: PASTE_PROXY, pastedProxy: "u:p@h:1" }), null],
    ["paste proxy, blank line", form({ proxyLabel: PASTE_PROXY, pastedProxy: "  " }), "Paste a proxy line or pick another option."],
    ["bad curl wins over the proxy line", form({ curl: "x", proxyLabel: PASTE_PROXY }), "Must start with `curl ...`"],
  ])("%s", (_, f, err) => expect(submitError(f)).toBe(err));
});

describe("canSubmit", () => {
  it.each([["", false], ["  ", false], ["x", true], [GOOD, true]])("%j → %s", (curl, ok) => expect(canSubmit(form({ curl }))).toBe(ok));
});

describe("buildBootstrapBody", () => {
  // JSON.stringify pins the key order the relay receives.
  it.each([
    ["defaults", form(), `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true}`],
    ["the curl as pasted, untrimmed", form({ curl: `  ${GOOD}\n` }), `{"mode":"paste-curl","curl":${JSON.stringify(`  ${GOOD}\n`)},"make_active":true}`],
    ["make_active off", form({ makeActive: false }), `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":false}`],
    ["nickname and override trimmed", form({ nickname: "  Mia ", staticOverride: " sp " }),
      `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true,"nickname":"Mia","static_param_override":"sp"}`],
    ["blank nickname / override left out", form({ nickname: "  ", staticOverride: "\t" }), `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true}`],
    ["proxy fields never in it", form({ proxyLabel: PASTE_PROXY, pastedProxy: "u:p@h:1" }), `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true}`],
  ])("%s", (_, f, json) => expect(JSON.stringify(buildBootstrapBody(f))).toBe(json));
});

describe("pasteCurlReducer", () => {
  const S = (over: Partial<PasteCurlState> = {}): PasteCurlState => ({ ...initialPasteCurl(BLANK), curl: GOOD, ...over });
  const PENDING = { accountId: "of-1", label: "p1" };
  const ERR = { ok: false, text: "e" };
  const cases: [string, PasteCurlState, PasteCurlAction, Partial<PasteCurlState>][] = [
    ["setField", S(), { type: "setField", field: "nickname", value: "Mia" }, { nickname: "Mia" }],
    ["setField makeActive", S(), { type: "setField", field: "makeActive", value: false }, { makeActive: false }],
    ["submitStart clears result and pending", S({ result: ERR, pending: PENDING }), { type: "submitStart" }, { result: null, pending: null, curl: GOOD }],
    ["retryStart drops pending, keeps the error", S({ result: ERR, pending: PENDING }), { type: "retryStart" }, { result: ERR, pending: null }],
    ["submitErr", S(), { type: "submitErr", text: "bad" }, { result: { ok: false, text: "bad" }, pending: null, curl: GOOD }],
    ["attachErr keeps the curl, sets pending", S(), { type: "attachErr", text: "t", ...PENDING }, { result: { ok: true, text: "t" }, pending: PENDING, curl: GOOD }],
    ["submitOk clears the curl and pending", S({ pending: PENDING }), { type: "submitOk", text: "✓" }, { result: { ok: true, text: "✓" }, pending: null, curl: "" }],
  ];
  it.each(cases)("%s", (_, s, a, want) => expect(pasteCurlReducer(s, a)).toEqual({ ...s, ...want }));
  it("retryStart with nothing pending is a no-op", () => {
    const s = S();
    expect(pasteCurlReducer(s, { type: "retryStart" })).toBe(s);
  });
  it("initialPasteCurl takes the flow's nickname and proxy label", () => {
    expect(initialPasteCurl({ nickname: "Bella", proxyLabel: "p1" })).toEqual({
      curl: "", nickname: "Bella", makeActive: true, proxyLabel: "p1", pastedProxy: "", staticOverride: "", result: null, pending: null,
    });
  });
});

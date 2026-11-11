import { describe, expect, it } from "vitest";

import {
  buildBootstrapBody, canSubmit, continueText, curlHint, extensionBusy, initialPasteCurl, pasteCurlReducer, validateCurl,
  type PasteCurlAction, type PasteCurlForm, type PasteCurlState,
} from "@/components/setup/pasteCurl";

const GOOD = "curl 'https://onlyfans.com/api2/v2/users/me' -H 'user-agent: Mozilla/5.0' -H 'x-bc: abc' -b 'auth_id=1; sess=s'";
const form = (over: Partial<PasteCurlForm> = {}): PasteCurlForm => ({ ...initialPasteCurl(), curl: GOOD, ...over });

describe("validateCurl", () => {
  // Prefix, bash copy, cookies and user-agent are checked here; the signed headers stay the relay's (its 422 says which).
  const U = "curl 'https://onlyfans.com/api2/v2/users/me'";
  const HOW = "Open the extension, click Copy cURL again and paste the whole copy.";
  const NO_COOKIES = `No cookies (-b '…') in this curl. ${HOW}`;
  const NO_UA = `No user-agent (-H 'user-agent: …') in this curl. ${HOW}`;
  const NO_BOTH = `No cookies (-b '…') and no user-agent (-H 'user-agent: …') in this curl. ${HOW}`;
  const PREFIX = "Must start with `curl ...`";
  it.each([
    ["a good curl", GOOD, null],
    ["surrounding whitespace", `\n  ${GOOD}  \n`, null],
    ["extra headers", `${GOOD} -H 'x-relay-static-param: sp' -H 'accept: */*' -H 'sec-fetch-mode: cors'`, null],
    ["Chrome's multi-line copy", `${U} \\\n  -H 'user-agent: UA' \\\n  -b 'sess=s'`, null],
    ["the extension's copy (-H lines, -b last)", `${U} \\\n  -H 'accept: */*' \\\n  -H 'user-agent: UA' \\\n  -H 'x-bc: x' \\\n  -b 'sess=s'`, null],
    ["cookie via -H, header names any case", `${U} -H 'Cookie: sess=s' -H 'User-Agent: UA'`, null],
    ["--cookie and --user-agent", `${U} --cookie 'sess=s' --user-agent 'UA'`, null],
    ["UA via -A", `${U} -A 'UA' -b 'sess=s'`, null],
    ["$'…' quoting", `${U} -H $'user-agent: UA' -b $'sess=s'`, null],
    ["double quotes", `curl "https://onlyfans.com/api2/v2/users/me" -H "user-agent: UA" -b "sess=s"`, null],
    ["no cookie (-b)", `${U} -H 'user-agent: UA'`, NO_COOKIES],
    ["no user-agent", `${U} -b 'sess=s'`, NO_UA],
    ["neither", `${U} -H 'x-bc: x'`, NO_BOTH],
    ["'cookie' only inside a value", `${U} -H 'user-agent: UA' -H 'x-note: cookie: no'`, NO_COOKIES],
    ["-B is not -b", `${U} -H 'user-agent: UA' -B 'sess=s'`, NO_COOKIES],
    // Copy as cURL (cmd): ^-escaped quotes the relay's shlex can't read, so it is refused with the bash hint.
    ["Windows cmd copy", `curl ^"https://onlyfans.com/api2/v2/users/me^" ^\n  -H ^"user-agent: UA^" ^\n  -b ^"sess=s^"`,
      `That is a Windows (cmd) copy. ${HOW}`],
    ["empty", "", PREFIX],
    ["blank", "   ", PREFIX],
    ["not a curl", "wget https://onlyfans.com", PREFIX],
    ["a fetch() copy", "fetch(\"https://onlyfans.com/api2/v2/users/me\")", PREFIX],
    ["case-sensitive", "CURL 'https://onlyfans.com'", PREFIX],
  ])("%s", (_, text, err) => expect(validateCurl(text)).toBe(err));
});

describe("curlHint", () => {
  it.each([["", null], ["   \n ", null], [GOOD, null], ["wget x", "Must start with `curl ...`"]])(
    "%j → %s", (curl, hint) => expect(curlHint(curl)).toBe(hint));
  it("names what is missing", () => expect(curlHint("curl 'https://onlyfans.com/api2/v2/users/me' -b 's=1'")).toMatch(/^No user-agent/));
});

describe("canSubmit", () => {
  it.each([["", false], ["  ", false], ["x", false], ["curl 'https://onlyfans.com/api2/v2/users/me'", false], [GOOD, true]])("%j → %s", (curl, ok) => expect(canSubmit({ curl, busy: false })).toBe(ok));
  it("off while a capture, its attach or a Retry runs (one submit at a time)", () => expect(canSubmit({ curl: GOOD, busy: true })).toBe(false));
});

describe("continueText", () => {
  it.each([
    [false, "Linked account of-1 without a proxy"],
    [true, "Linked account of-1; its proxy is attached, but the session was not reloaded"],
  ])("bound %s", (bound, text) => expect(continueText({ accountId: "of-1", bound })).toBe(text));
});

describe("buildBootstrapBody", () => {
  // JSON.stringify pins the key order the relay receives.
  it.each<[string, PasteCurlForm, string, string]>([
    ["defaults", form(), "", `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true}`],
    ["the curl as pasted, untrimmed", form({ curl: `  ${GOOD}\n` }), "", `{"mode":"paste-curl","curl":${JSON.stringify(`  ${GOOD}\n`)},"make_active":true}`],
    ["the flow's nickname and the override trimmed", form({ staticOverride: " sp " }), "  Mia ",
      `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true,"nickname":"Mia","static_param_override":"sp"}`],
    ["blank nickname / override left out", form({ staticOverride: "\t" }), "  ", `{"mode":"paste-curl","curl":${JSON.stringify(GOOD)},"make_active":true}`],
  ])("%s", (_, f, nickname, json) => expect(JSON.stringify(buildBootstrapBody(f, nickname))).toBe(json));
});

describe("pasteCurlReducer", () => {
  const S = (over: Partial<PasteCurlState> = {}): PasteCurlState => ({ ...initialPasteCurl(), curl: GOOD, ...over });
  const PENDING = { accountId: "of-1", bound: false };
  const ERR = { ok: false, text: "e" };
  const cases: [string, PasteCurlState, PasteCurlAction, Partial<PasteCurlState>][] = [
    ["setField", S(), { type: "setField", field: "staticOverride", value: "sp" }, { staticOverride: "sp" }],
    ["submitStart clears result and pending, busy", S({ result: ERR, pending: PENDING }), { type: "submitStart" }, { busy: true, result: null, pending: null, curl: GOOD }],
    ["retryStart drops pending, keeps the error, busy", S({ result: ERR, pending: PENDING }), { type: "retryStart" }, { busy: true, result: ERR, pending: null }],
    ["submitErr", S({ busy: true }), { type: "submitErr", text: "bad" }, { busy: false, result: { ok: false, text: "bad" }, pending: null, curl: GOOD }],
    ["attachErr keeps the curl, sets pending", S({ busy: true }), { type: "attachErr", text: "t", ...PENDING }, { busy: false, result: { ok: true, text: "t" }, pending: PENDING, curl: GOOD }],
    ["submitOk clears the curl and pending", S({ busy: true, pending: PENDING }), { type: "submitOk", text: "✓" }, { busy: false, result: { ok: true, text: "✓" }, pending: null, curl: "" }],
  ];
  it.each(cases)("%s", (_, s, a, want) => expect(pasteCurlReducer(s, a)).toEqual({ ...s, ...want }));
  it("retryStart with nothing pending is a no-op", () => {
    const s = S();
    expect(pasteCurlReducer(s, { type: "retryStart" })).toBe(s);
  });
  it("initialPasteCurl is blank", () => {
    expect(initialPasteCurl()).toEqual({ curl: "", staticOverride: "", busy: false, result: null, pending: null });
  });
  it.each<[string, Partial<PasteCurlState>, boolean]>([
    ["idle", {}, false],
    ["capturing / attaching / retrying", { busy: true }, true],
    ["waiting on Retry / Continue", { pending: PENDING }, true],
  ])("extensionBusy: %s", (_, over, want) => expect(extensionBusy(S(over))).toBe(want));
});

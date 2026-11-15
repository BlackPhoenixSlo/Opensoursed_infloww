import { describe, expect, it } from "vitest";

import { localPath, nextHref } from "./nextPath";

describe("localPath", () => {
  it.each<[string | null | undefined, string | null]>([
    ["/", "/"],
    ["/chat?x=1#y", "/chat?x=1#y"],
    ["/auth/oauth/authorize?client_id=a.b&state=s", "/auth/oauth/authorize?client_id=a.b&state=s"],
    [null, null],
    [undefined, null],
    ["", null],
    ["//evil.example/x", null],
    ["/\\evil.example", null],
    ["/a\\b", null],
    ["\\\\evil.example", null],
    ["https://evil.example/", null],
    ["javascript:alert(1)", null],
    ["chat", null],
    ["/\t/evil.example", null],
    ["/a\nb", null],
    ["/a\u0000b", null],
    ["/a\u007fb", null],
  ])("%j → %j", (raw, want) => {
    expect(localPath(raw)).toBe(want);
  });
});

describe("nextHref", () => {
  it.each<[string | null, string | undefined, string]>([
    ["/chat", "/plan", "/chat"],
    ["//evil.example", "/plan", "/plan"],
    ["javascript:alert(1)", undefined, "/"],
    [null, "/plan", "/plan"],
    [null, "https://evil.example", "/"],
    [null, undefined, "/"],
  ])("query %j, fallback %j → %j", (query, fallback, want) => {
    expect(nextHref(query, fallback)).toBe(want);
  });
});

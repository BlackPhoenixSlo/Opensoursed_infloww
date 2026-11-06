import { afterEach, describe, expect, it } from "vitest";

import { cachedImg, imgIdentity, rememberImg, resetImgBlobs } from "./imgBlobs";

afterEach(() => resetImgBlobs());

const img = (u: string, a = "A1") => `/img?${new URLSearchParams({ u, account_id: a })}`;

describe("imgIdentity", () => {
  it.each<[string, string, string | null]>([
    ["signature dropped", img("https://cdn2.onlyfans.com/files/a/b/300x300_x.jpg?Policy=p1&Signature=s1"), "A1|cdn2.onlyfans.com/files/a/b/300x300_x.jpg"],
    ["re-signed: the same", img("https://cdn2.onlyfans.com/files/a/b/300x300_x.jpg?Policy=p2&Signature=s2"), "A1|cdn2.onlyfans.com/files/a/b/300x300_x.jpg"],
    ["another Creator", img("https://cdn2.onlyfans.com/files/a/b/300x300_x.jpg?Policy=p1", "B"), "B|cdn2.onlyfans.com/files/a/b/300x300_x.jpg"],
    ["by-hash", "/img/by-hash/abc?account_id=A1", null],
    ["blob", "blob:http://x/1", null],
    ["no u", "/img?account_id=A1", null],
    ["bad u", img("not a url"), null],
  ])("%s", (_n, proxied, want) => {
    expect(imgIdentity(proxied)).toBe(want);
  });
});

describe("cache", () => {
  it("a load is shared; a failed one is forgotten", async () => {
    const ok = rememberImg("k1", Promise.resolve("blob:1"));
    expect(cachedImg("k1")).toBe(ok);
    expect(await cachedImg("k1")).toBe("blob:1");
    await rememberImg("k2", Promise.reject(new Error("abort")));
    await Promise.resolve();
    expect(cachedImg("k2")).toBeUndefined();
  });
});

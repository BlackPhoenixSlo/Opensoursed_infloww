import { describe, expect, it } from "vitest";

import { type VaultMedia } from "@/lib/relay";

import { toItems } from "./vaultDownloadReducer";
import { DRM_TEXT, MIN_LEFT_MS, appLink, buildLinksFile, escapeHtml, urlExpiry, type LinksOpts } from "./vaultLinksFile";

const NOW = Date.UTC(2026, 10, 8, 16, 32);
const EXP = Date.UTC(2026, 10, 9, 16, 0) / 1000;   // OF: listed 16:32 -> DateLessThan next day 16:00 (measured)
const policy = (exp: number) => btoa(JSON.stringify({ Statement: [{ Resource: "x*",
  Condition: { DateLessThan: { "AWS:EpochTime": exp }, IpAddress: { "AWS:SourceIp": "1.2.3.4/32" } } }] }))
  .replace(/\+/g, "-").replace(/=/g, "_").replace(/\//g, "~");
const signed = (id: number, exp = EXP, ext = "jpg") =>
  `https://cdn2.onlyfans.com/files/a/${id}.${ext}?Policy=${policy(exp)}&Signature=s&Key-Pair-Id=K`;
const media = (id: number, url: string | null, type = "photo") =>
  ({ id, type, files: { full: { url } }, listStates: [] }) as unknown as VaultMedia;
const opts: LinksOpts = { origin: "https://app.example.com/", accountId: "acc 1", creator: "Mia", label: "3 selected",
  direct: true, now: NOW };
const lines = (txt: string) => txt.split("\n").filter((l) => l && !l.startsWith("#"));

describe("urlExpiry", () => {
  it.each<[string, string, number | null]>([
    ["custom Policy (CloudFront base64 substitutions)", signed(1), EXP * 1000],
    ["canned Expires", "https://cdn2.onlyfans.com/a.jpg?Expires=1762704000&Signature=s", 1762704000 * 1000],
    ["unsigned", "https://cdn2.onlyfans.com/a.jpg", null],
    ["garbage Policy", "https://cdn2.onlyfans.com/a.jpg?Policy=%25%25", null],
    ["not a url", "nope", null],
  ])("%s", (_n, u, want) => {
    expect(urlExpiry(u)).toBe(want);
  });
});

describe("buildLinksFile", () => {
  const items = toItems([media(11, signed(11)), media(12, signed(12, EXP, "mp4"), "video"), media(13, null, "video")], null);

  it.each<[string, Partial<LinksOpts>, string[]]>([
    ["direct: CDN url, DRM has none", {}, ["cdn", "cdn", "drm"]],
    ["proxied: app link even for a fresh url", { direct: false }, ["app", "app", "drm"]],
    ["direct but the url expires within MIN_LEFT: app", { now: EXP * 1000 - MIN_LEFT_MS + 1 }, ["app", "app", "drm"]],
  ])("link kind: %s", (_n, o, want) => {
    expect(buildLinksFile(items, { ...opts, ...o }).rows.map((r) => r.link)).toEqual(want);
  });

  it("txt: one line per item, `<id>.<ext>  <link>`, CDN urls verbatim; named after the earliest expiry", () => {
    const f = buildLinksFile(items, opts);
    expect(f.txtName).toBe("links-valid-until-20261109-1600UTC.txt");
    expect(f.htmlName).toBe("links-valid-until-20261109-1600UTC.html");
    expect(f.validUntil).toBe(EXP * 1000);
    expect(f.txt).toContain("# Valid until 2026-11-09 16:00 UTC");
    expect(f.txt).toContain("open while logged in to https://app.example.com");   // the html's backup app links
    expect(lines(f.txt)).toEqual([`11.jpg  ${signed(11)}`, `12.mp4  ${signed(12, EXP, "mp4")}`, `13.mp4  ${DRM_TEXT}`]);
  });

  it("proxied: app links absolute to the origin, header says log in there; no expiry in the name", () => {
    const f = buildLinksFile(items, { ...opts, direct: false, token: "tok&x" });
    expect(f.txtName).toBe("links-valid-while-logged-in.txt");
    expect(f.validUntil).toBeNull();
    expect(f.txt).toContain("open while logged in to https://app.example.com");
    expect(lines(f.txt)[0]).toBe("11.jpg  https://app.example.com/admin/vault-ai/download?account_id=acc+1&media_id=11&t=tok%26x");
    expect(f.txt).not.toContain("cdn2.onlyfans.com");
  });

  it("the earliest CDN expiry names the file", () => {
    const f = buildLinksFile(toItems([media(1, signed(1, EXP + 7200)), media(2, signed(2, EXP))], null), opts);
    expect(f.validUntil).toBe(EXP * 1000);
  });

  it("html: every item a link in a new tab, CDN rows carry the app link as backup, all text escaped", () => {
    const evil = toItems([media(21, signed(21))], "<b>\"x'&</b>");
    const f = buildLinksFile(evil, { ...opts, creator: "<script>alert(1)</script>" });
    expect(f.html).not.toContain("<script>alert");
    expect(f.html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(f.html).not.toContain("<b>");
    expect(f.html).toContain('target="_blank" rel="noopener noreferrer"');
    expect(f.html).toContain(escapeHtml(signed(21)));
    expect(f.html).toContain(escapeHtml(appLink(opts, 21)));
    const all = buildLinksFile(items, opts).html;
    expect(all.match(/<tr data-id=/g)?.length).toBe(3);
    expect(all).toContain(`data-link="drm"><td>3</td><td class="m">13.mp4</td><td>video</td><td>Unfiled</td><td>${DRM_TEXT}</td>`);
  });

  it.each<[string, string]>([["a&b", "a&amp;b"], ["<>", "&lt;&gt;"], ["\"'", "&quot;&#39;"]])("escapeHtml(%s)", (i, o) => {
    expect(escapeHtml(i)).toBe(o);
  });
});

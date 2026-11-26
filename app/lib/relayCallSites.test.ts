import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { scanCallSites } from "@/lib/relayCallSites";

type Entry = { class: "agency" | "cross" | "ctx" | "dynamic"; why: string };
const LEDGER: Record<string, Entry> = JSON.parse(readFileSync(resolve(__dirname, "relayCallSites.ledger.json"), "utf8"));
const sites = scanCallSites(resolve(__dirname, ".."));
const key = (s: { file: string; method: string; path: string }) => `${s.file} ${s.method} ${s.path}`;

describe("every relay call names its Creator, or is ledgered", () => {
  it("finds the call sites", () => {
    expect(sites.length).toBeGreaterThan(500);
  });
  it("no unledgered call that the Front door cannot route", () => {
    const open = sites.filter((s) => s.verdict !== "routed" && !(key(s) in LEDGER));
    expect(open.map((s) => `${s.file}:${s.line} ${s.method} ${s.path} (${s.verdict})`)).toEqual([]);
  });
  it("no stale ledger line", () => {
    const live = new Set(sites.filter((s) => s.verdict !== "routed").map(key));
    expect(Object.keys(LEDGER).filter((k) => !live.has(k))).toEqual([]);
  });
});

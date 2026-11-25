import { describe, expect, it } from "vitest";

import {
  canonFacts, claimDate, supersededClaims, visibleClaims, visibleResolved,
} from "./PersonaClaims";
import type { PersonaClaim, ResolvedClaim } from "@/lib/relay";

describe("visibleClaims", () => {
  it("keeps real claims in stored order — newest last, as the engines write them", () => {
    const claims: PersonaClaim[] = [
      { topic: "current location", claim: "estoy acá en Chile", at: "2026-07-25T19:00:00" },
      { topic: "nationality", claim: "soy argentina de verdad", at: "2026-07-25T19:46:42" },
      { topic: "city", claim: "en córdoba", at: "2026-07-25T20:44:39" },
    ];
    expect(visibleClaims(claims).map((c) => c.claim)).toEqual([
      "estoy acá en Chile", "soy argentina de verdad", "en córdoba",
    ]);
  });

  it("drops rows with no usable claim text", () => {
    expect(visibleClaims([
      { topic: "job", claim: "" },
      { topic: "job", claim: "   " },
      { topic: "city", claim: "en córdoba" },
      {},
    ])).toHaveLength(1);
  });

  it("treats absent/undefined as empty rather than throwing", () => {
    expect(visibleClaims(undefined)).toEqual([]);
    expect(visibleClaims([])).toEqual([]);
  });
});

describe("canonFacts — step 1, what is pinned into every prompt", () => {
  const fields = [
    { key: "age", label: "Age" },
    { key: "job", label: "Job" },
    { key: "height", label: "Height" },
  ];

  it("keeps the contract's order, not the object's — it is 'what fans ask most'", () => {
    const facts = { job: "barista", age: "22", height: "165 cm" };
    expect(canonFacts(facts, fields).map((f) => f.label)).toEqual(["Age", "Job", "Height"]);
  });

  it("shows only filled slots", () => {
    expect(canonFacts({ age: "22", job: "", height: "   " }, fields)
      .map((f) => f.key)).toEqual(["age"]);
  });

  it("survives an unconfigured model without throwing", () => {
    expect(canonFacts(undefined, fields)).toEqual([]);
    expect(canonFacts({ age: "22" }, undefined)).toEqual([]);
  });
});

describe("visibleResolved", () => {
  // Not re-sorted/re-merged here: the override rule lives in _persona.resolved_claims; a second implementation made browser and server disagree.
  it("keeps the server's merge and order — it is the prompt's own line-up", () => {
    const rows: ResolvedClaim[] = [
      { label: "where you are", value: "en rosario", column: "persona_location_claimed", at: null },
      { label: "nationality", value: "soy argentina", column: null, at: "2026-07-25T19:46:42" },
    ];
    expect(visibleResolved(rows).map((r) => r.label)).toEqual(["where you are", "nationality"]);
  });

  it("drops valueless rows and survives an absent field", () => {
    expect(visibleResolved([
      { label: "job", value: "  ", column: "persona_job_claimed", at: null },
    ])).toEqual([]);
    expect(visibleResolved(undefined)).toEqual([]);
  });
});

describe("supersededClaims", () => {
  it("shows only what is NO LONGER the current answer", () => {
    const claims: PersonaClaim[] = [
      { topic: "current location", claim: "estoy acá en Chile", at: "2026-07-25T19:00:00" },
      { topic: "city", claim: "en córdoba", at: "2026-07-25T20:44:39" },
    ];
    const resolved: ResolvedClaim[] = [
      { label: "where you are", value: "en córdoba", column: "persona_location_claimed", at: null },
    ];
    expect(supersededClaims(claims, resolved).map((c) => c.claim))
      .toEqual(["estoy acá en Chile"]);
  });

  it("is empty when every claim is still current", () => {
    const claims: PersonaClaim[] = [{ topic: "city", claim: "en córdoba", at: "1" }];
    const resolved: ResolvedClaim[] = [
      { label: "city", value: "en córdoba", column: null, at: "1" },
    ];
    expect(supersededClaims(claims, resolved)).toEqual([]);
  });
});

describe("claimDate", () => {
  it("renders a real timestamp as a date", () => {
    expect(claimDate("2026-07-25T20:44:39")).not.toBe("");
  });

  it("renders nothing for junk instead of 'Invalid Date'", () => {
    expect(claimDate("not-a-date")).toBe("");
    expect(claimDate("")).toBe("");
    expect(claimDate(undefined)).toBe("");
  });
});

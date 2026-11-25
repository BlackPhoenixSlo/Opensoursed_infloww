import { describe, expect, it } from "vitest";

const FANSLY_MSG = "900715634200489987";

function unsendId(raw: unknown): string | null {
  const id = String(raw ?? "");
  if (!/^\d+$/.test(id) || /^0+$/.test(id)) return null;
  return id;
}

describe("unsend target id", () => {
  it("sends the snowflake unchanged, not a rounded one", () => {
    expect(unsendId(FANSLY_MSG)).toBe(FANSLY_MSG);
    // What the old code would have DELETEd instead:
    expect(String(Number(FANSLY_MSG))).toBe("900715634200490000");
    expect(unsendId(FANSLY_MSG)).not.toBe(String(Number(FANSLY_MSG)));
  });

  it("still handles a numeric OnlyFans id", () => {
    expect(unsendId(10491720677794)).toBe("10491720677794");
  });

  it("refuses ids that are not ids, so no DELETE is ever issued for them", () => {
    for (const bad of [null, undefined, "", "abc", "0", "000", "-5", "1.5"]) {
      expect(unsendId(bad)).toBeNull();
    }
  });

  it("matches the right bubble as text (the optimistic cache filter)", () => {
    const rows = [{ id: FANSLY_MSG }, { id: "900715634200489988" }];
    const target = unsendId(FANSLY_MSG)!;
    const left = rows.filter((m) => String(m.id) !== target);
    expect(left).toHaveLength(1);
    expect(left[0].id).toBe("900715634200489988");
    // Numeric comparison would have collapsed BOTH ids to the same value.
    expect(Number(rows[0].id)).toBe(Number(rows[1].id));
  });
});

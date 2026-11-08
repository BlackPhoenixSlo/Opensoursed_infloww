import { afterEach, describe, expect, it } from "vitest";

import { clearSendStash, DELIVERED_CAP, sendStash } from "@/lib/sendStash";

afterEach(() => clearSendStash());

describe("sendStash delivered", () => {
  it("sent is delivered; discarded is not", () => {
    sendStash.set(-1, { input: { text: "a" }, files: [] });
    sendStash.set(-2, { input: { text: "b" }, files: [] });
    sendStash.sent(-1);
    sendStash.discard(-2);
    expect([sendStash.delivered(-1), sendStash.delivered(-2)]).toEqual([true, false]);
    expect(sendStash.get(-1)).toBeUndefined();
  });

  it("keeps only the last DELIVERED_CAP, oldest out first", () => {
    for (let i = 1; i <= DELIVERED_CAP + 1; i++) sendStash.sent(-i);
    expect(sendStash.delivered(-1)).toBe(false);
    expect(sendStash.delivered(-2)).toBe(true);
    expect(sendStash.delivered(-(DELIVERED_CAP + 1))).toBe(true);
  });

  it("an identity switch forgets them", () => {
    sendStash.sent(-1);
    clearSendStash();
    expect(sendStash.delivered(-1)).toBe(false);
  });
});

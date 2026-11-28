import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { patchQueryData } from "./cacheWrite";

describe("patchQueryData", () => {
  it("a seed write into an empty cache keeps dataUpdatedAt 0 (ChatSurface ofSettled relies on it)", () => {
    const qc = new QueryClient();
    patchQueryData<number[]>(qc, ["k"], () => [1]);
    expect(qc.getQueryData(["k"])).toEqual([1]);
    expect(qc.getQueryState(["k"])?.dataUpdatedAt).toBe(0);
  });

  it("keeps the fetched read time on later patches", () => {
    const qc = new QueryClient();
    qc.setQueryData<number[]>(["k"], [1], { updatedAt: 1234 });
    patchQueryData<number[]>(qc, ["k"], (prev) => [...(prev ?? []), 2]);
    expect(qc.getQueryState(["k"])?.dataUpdatedAt).toBe(1234);
  });
});

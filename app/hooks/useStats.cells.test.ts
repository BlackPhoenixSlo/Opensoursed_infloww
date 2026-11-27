import { expect, it, vi } from "vitest";

import { resetCellFlagForTests } from "@/lib/cellFlag";
import { postBatchAttribute } from "./useStats";

it("refuses Clock-event reassignment before sending a cell request", async () => {
  const meta = document.createElement("meta");
  meta.name = "oi-cells";
  document.head.append(meta);
  resetCellFlagForTests();
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  try {
    await expect(postBatchAttribute({ employeeId: "no_one", clockEventId: 10 }))
      .rejects.toThrow("Clock-event sales reassignment is off in cell mode");
    expect(fetch).not.toHaveBeenCalled();
  } finally {
    meta.remove();
    resetCellFlagForTests();
    vi.unstubAllGlobals();
  }
});

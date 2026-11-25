import { afterEach, describe, expect, it, vi } from "vitest";

describe("tabId", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    vi.resetModules();
  });

  const load = async () => (await import("@/lib/viewLease")).tabId;

  it("is stable within one document load", async () => {
    const tabId = await load();
    expect(tabId()).toBe(tabId());
  });

  it("is not read from sessionStorage (a popout or a duplicated tab copies it)", async () => {
    window.sessionStorage.setItem("chatterly:view-lease-tab", "copied-from-opener");
    const tabId = await load();
    expect(tabId()).not.toBe("copied-from-opener");
  });

  it("differs per document load", async () => {
    const first = (await load())();
    vi.resetModules();
    const second = (await load())();
    expect(second).not.toBe(first);
  });
});

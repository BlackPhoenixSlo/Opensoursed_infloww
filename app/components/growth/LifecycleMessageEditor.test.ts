import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn() } };
});

import { relay } from "@/lib/relay";

import LifecycleMessageEditor from "./LifecycleMessageEditor";
import { badDelay, cleanFollowUps } from "./lifecycleForm";

const WEEK = 7 * 24 * 60;

describe("badDelay", () => {
  it.each([
    ["", "", false],
    ["   ", "abc", false],
    ["hi", "", true],
    ["hi", "0", true],
    ["hi", "-5", true],
    ["hi", "abc", true],
    ["hi", "1.5", true],
    ["hi", "1", false],
    ["hi", " 5 ", false],
    ["hi", String(WEEK), false],
    ["hi", String(WEEK + 1), true],
    ["hi", "1e3", false],
  ])("text %j delay %j -> %s", (text, delay, bad) => {
    expect(badDelay({ text, delay })).toBe(bad);
  });
});

describe("cleanFollowUps", () => {
  it("empty -> []", () => {
    expect(cleanFollowUps([])).toEqual([]);
  });

  it("drops blank steps, trims text, keeps order", () => {
    expect(cleanFollowUps([
      { text: " first ", delay: "5" },
      { text: "", delay: "10" },
      { text: "  \n ", delay: "15" },
      { text: "second", delay: "60" },
      { text: "third\t", delay: "1" },
    ])).toEqual([
      { text: "first", delay_minutes: 5 },
      { text: "second", delay_minutes: 60 },
      { text: "third", delay_minutes: 1 },
    ]);
  });

  it("does not validate the delay (badDelay gates the save)", () => {
    expect(cleanFollowUps([{ text: "x", delay: "abc" }])).toEqual([{ text: "x", delay_minutes: Number.NaN }]);
  });
});

describe("LifecycleMessageEditor feeds the GET refusal into the switch", () => {
  const get = relay.get as unknown as Mock;
  const put = relay.put as unknown as Mock;
  const EXTRAS = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0, frequency: "once" };
  const config = (enabled: boolean) => ({ enabled, text: "hi", hours: 24, messages: [], ...EXTRAS });
  const serve = (enabled: boolean, refusal: string | null) => get.mockImplementation((p: string) => {
    if (p.startsWith("/admin/lifecycle-message-config/buyers")) return Promise.resolve({ window_days: 7, buyers: [] });
    if (p.startsWith("/admin/lifecycle-message-config")) {
      return Promise.resolve({ account_id: "acc", kind: "expiry_message", config: config(enabled), defaults: config(false), refusal });
    }
    return Promise.resolve({ subscribePrice: 9.99 });
  });
  const mount = () => render(createElement(QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    createElement(LifecycleMessageEditor, { accountId: "acc", kind: "expiry_message", onTouched: () => {} })));
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("Fansly, off: the switch is disabled with not on this platform", async () => {
    serve(false, "platform_lacks:renewal_state");
    mount();
    expect(await screen.findByText("Nearing expiry: not on this platform")).toBeTruthy();
    expect((screen.getByRole("switch", { name: "On" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("Fansly, stored on: switched off it saves off", async () => {
    serve(true, "platform_lacks:renewal_state");
    put.mockResolvedValue({});
    mount();
    const sw = await screen.findByRole("switch", { name: "On" }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(sw);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1]).toMatchObject({ kind: "expiry_message", config: { enabled: false } });
  });

  it("OnlyFans control: no refusal, the switch turns on", async () => {
    serve(false, null);
    mount();
    const sw = await screen.findByRole("switch", { name: "On" }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false);
    expect(screen.queryByText(/not on this platform/)).toBeNull();
  });
});

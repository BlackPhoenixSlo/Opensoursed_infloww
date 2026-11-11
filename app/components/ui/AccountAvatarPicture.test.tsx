import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AccountAvatarPicture, type AvatarHealth } from "./AccountAvatarPicture";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
const get = vi.mocked(relay.get);
const me = (id = "11", avatar: string | null = "https://cdn/old.jpg") => ({ id, avatar });
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
function picture(health?: AvatarHealth, id = "11") {
  return <AccountAvatarPicture account={{ id, nickname: "Ava", color: "#abc" }} letters={2} initialClassName="" health={health} />;
}
beforeEach(() => { client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); get.mockReset(); });
afterEach(cleanup);

describe("avatar identity and health reuse", () => {
  it("observes valid cache while pending, prefers health, never seeds partial full-profile data", async () => {
    client.setQueryData(["of-profile", "11"], { ...me(), username: "keep-full-profile" });
    const view = render(picture({ settled: false }), { wrapper });
    expect(view.container.querySelector("img")).toHaveAttribute("src", proxyImage(me().avatar, "11"));
    expect(get).not.toHaveBeenCalled();
    view.rerender(picture({ settled: true, profile: me("11", "https://cdn/health.jpg") }));
    expect(view.container.querySelector("img")).toHaveAttribute("src", proxyImage("https://cdn/health.jpg", "11"));
    expect(client.getQueryData(["of-profile", "11"])).toEqual({ ...me(), username: "keep-full-profile" });
    expect(get).not.toHaveBeenCalled();
    view.rerender(picture({ settled: true, profile: me("11", null) }));
    expect(view.container.querySelector("img")).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it("rejects another identity in cache and health; fetches only after health settles", async () => {
    client.setQueryData(["of-profile", "11"], me("22"));
    const view = render(picture({ settled: false, profile: me("22") }), { wrapper });
    expect(view.container.querySelector("img")).toBeNull();
    expect(get).not.toHaveBeenCalled();
    // A mismatched cache body must not suppress the own-profile fallback.
    get.mockResolvedValue(me());
    view.rerender(picture({ settled: true, profile: me("22") }));
    await waitFor(() => expect(view.container.querySelector("img")).not.toBeNull());
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/api/of/v2/users/me", expect.objectContaining({ accountId: "11" }), expect.any(AbortSignal));
  });

  it.each([null, { avatar: "https://cdn/wrong.jpg" }, me("22")])("rejects missing/wrong identity after failed health: %s", async (reply) => {
    get.mockResolvedValue(reply);
    const view = render(picture({ settled: true }), { wrapper });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(view.container.querySelector("img")).toBeNull();
  });

  it("lets pending health repair a failed cached image before any recovery fetch", async () => {
    client.setQueryData(["of-profile", "11"], me());
    const view = render(picture({ settled: false }), { wrapper });
    fireEvent.error(view.container.querySelector("img")!);
    expect(get).not.toHaveBeenCalled();
    view.rerender(picture({ settled: true, profile: me("11", "https://cdn/health-new.jpg") }));
    expect(view.container.querySelector("img")).toHaveAttribute("src", proxyImage("https://cdn/health-new.jpg", "11"));
    expect(get).not.toHaveBeenCalled();
  });

  it("recovers an expired URL once, then initials; account and source changes reset it", async () => {
    get.mockResolvedValue(me("11", "https://cdn/new.jpg"));
    const view = render(picture({ settled: true, profile: me() }), { wrapper });
    fireEvent.error(view.container.querySelector("img")!);
    await waitFor(() => expect(view.container.querySelector("img")).toHaveAttribute("src", proxyImage("https://cdn/new.jpg", "11")));
    fireEvent.error(view.container.querySelector("img")!);
    expect(view.container.querySelector("img")).toBeNull();
    expect(view.container).toHaveTextContent("AV");
    expect(get).toHaveBeenCalledTimes(1);
    view.rerender(picture({ settled: true, profile: me("11", "https://cdn/changed.jpg") }));
    expect(view.container.querySelector("img")).toHaveAttribute("src", proxyImage("https://cdn/changed.jpg", "11"));
    view.rerender(picture({ settled: true, profile: me("22", "https://cdn/changed.jpg") }, "22"));
    expect(view.container.querySelector("img")).toHaveAttribute("src", proxyImage("https://cdn/changed.jpg", "22"));
  });

  it.each([me(), me("22", "https://cdn/new.jpg"), null])("does not retry unchanged, mismatched or failed recovery: %s", async (reply) => {
    get.mockResolvedValue(reply);
    const view = render(picture({ settled: true, profile: me() }), { wrapper });
    await act(async () => { fireEvent.error(view.container.querySelector("img")!); });
    expect(view.container.querySelector("img")).toBeNull();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it.each(["11", "22"])("aborts old recovery on session/account change to %s and never paints its late response", async (nextId) => {
    let answer!: (value: unknown) => void;
    get.mockImplementation(() => new Promise((resolve) => { answer = resolve; }) as never);
    const view = render(picture({ settled: true, profile: me() }), { wrapper });
    fireEvent.error(view.container.querySelector("img")!);
    const signal = get.mock.calls[0][2] as AbortSignal;
    await act(async () => { await client.cancelQueries(); client.clear(); });
    view.rerender(picture({ settled: false }, nextId));
    expect(signal.aborted).toBe(true);
    await act(async () => answer(me("11", "https://cdn/late.jpg")));
    expect(view.container.querySelector("img")).toBeNull();
    view.rerender(picture({ settled: true, profile: me(nextId, null) }, nextId));
    expect(get).toHaveBeenCalledTimes(1);
  });
});

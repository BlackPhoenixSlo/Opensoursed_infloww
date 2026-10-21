/**
 * useSettingsBlob — a Blob tab's Settings blob, loaded and saved whole through
 * the Relay (`GET/PUT /admin/settings/{tab}`, ADR-0007), behind the Load gate.
 *
 * The relay is mocked at `fetch` by URL, so every assertion about a save is an
 * assertion about the WIRE: a disabled-looking Save that still sends a PUT is
 * exactly the failure the Load gate exists to stop (a whole-blob replace over
 * a blob that never loaded wipes the stored settings).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";

import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { SaveRow } from "@/components/settings/StickySaveBar";
import { useSettingsBlob } from "@/lib/settingsBlob";

const DEFAULTS = { a: 0, b: 0, c: "Alpha One" };

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type Call = { method: string; url: string; body: unknown };

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET /admin/settings/account answers next. */
let getReply: () => Response;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");

beforeEach(() => {
  getReply = () => jsonRes({ tab: "account", config: { a: 1, b: 2 } });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/admin/settings/account" && method === "GET") return getReply();
    if (url === "/admin/settings/account" && method === "PUT") {
      return jsonRes({ tab: "account", config: JSON.parse(String(init?.body)) });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(client: QueryClient = makeTestQueryClient()) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const hook = renderHook(() => useSettingsBlob("account", DEFAULTS), { wrapper });
  return { ...hook, client };
}

/** The Save button `SaveRow` renders from the hook's current `save`. */
function renderSave(save: Parameters<typeof SaveRow>[0]) {
  cleanup();
  renderWithProviders(createElement(SaveRow, save));
  return screen.getByRole("button", { name: /save/i });
}

describe("useSettingsBlob", () => {
  it("PUTs the full merged object to /admin/settings/account", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.value).toEqual({ a: 1, b: 2, c: "Alpha One" });

    act(() => result.current.set({ b: 3 }));
    expect(result.current.value).toEqual({ a: 1, b: 3, c: "Alpha One" });
    act(() => result.current.save.onSave());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({
      method: "PUT",
      url: "/admin/settings/account",
      body: { a: 1, b: 3, c: "Alpha One" },
    });
    await waitFor(() => expect(result.current.save.saved).toBe(true));
    expect(result.current.value).toEqual({ a: 1, b: 3, c: "Alpha One" });

    // `saved` lasts until the next edit.
    act(() => result.current.set({ a: 5 }));
    expect(result.current.save.saved).toBeFalsy();
  });

  it("a 500 on GET keeps Save disabled and sends no PUT (Load gate)", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    const { result } = mount();
    await waitFor(() => expect(result.current.save.gateNote?.failed).toBe(true));
    expect(result.current.loaded).toBe(false);
    expect(result.current.save.canSave).toBe(false);
    expect(result.current.value).toEqual(DEFAULTS);

    expect(renderSave(result.current.save)).toBeDisabled();

    act(() => result.current.set({ b: 9 }));
    act(() => result.current.save.onSave());
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
    expect(calls().every((c) => c.method === "GET")).toBe(true);
  });

  it("reset() restores the loaded value and sends nothing", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    const before = fetchMock.mock.calls.length;

    act(() => result.current.set({ a: 7, b: 3 }));
    expect(result.current.value).toEqual({ a: 7, b: 3, c: "Alpha One" });
    act(() => result.current.reset());

    expect(result.current.value).toEqual({ a: 1, b: 2, c: "Alpha One" });
    expect(fetchMock.mock.calls.length).toBe(before);
  });

  it("a failed refetch over a good load keeps Save on with the Couldn't refresh note", async () => {
    const { result, client } = mount();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.save.gateNote).toBeNull();

    getReply = () => jsonRes({ detail: "boom" }, 500);
    await act(async () => {
      await client.refetchQueries({ queryKey: ["settings-blob", "account"] });
    });

    await waitFor(() =>
      expect(result.current.save.gateNote?.text).toMatch(/^Couldn't refresh/));
    expect(result.current.save.canSave).toBe(true);
    expect(result.current.value).toEqual({ a: 1, b: 2, c: "Alpha One" });
    expect(renderSave(result.current.save)).toBeEnabled();
  });
  it("commit before load sends no PUT and does not call onSaved (Load gate)", async () => {
    let resolveGet: (r: Response) => void = () => {};
    fetchMock.mockImplementationOnce(() => new Promise<Response>((r) => { resolveGet = r; }));
    const { result } = mount();
    expect(result.current.loaded).toBe(false);
    const onSaved = vi.fn();

    act(() => result.current.commit({ b: 9 }, onSaved));
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
    expect(onSaved).not.toHaveBeenCalled();
    resolveGet(jsonRes({ tab: "account", config: { a: 1, b: 2 } }));
  });

  it("commit after load PUTs value merged with the patch and calls onSaved on success", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    act(() => result.current.set({ a: 4 }));
    const onSaved = vi.fn();

    act(() => result.current.commit({ c: "Beta Two" }, onSaved));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(puts()).toEqual([{
      method: "PUT",
      url: "/admin/settings/account",
      body: { a: 4, b: 2, c: "Beta Two" },
    }]);
  });

  it("commit whose PUT fails does not call onSaved", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    fetchMock.mockImplementationOnce(async () => jsonRes({ detail: "boom" }, 500));
    const onSaved = vi.fn();

    act(() => result.current.commit({ b: 3 }, onSaved));
    await waitFor(() => expect(result.current.save.error).toBeTruthy());
    expect(puts()).toHaveLength(1);
    expect(onSaved).not.toHaveBeenCalled();
  });
});

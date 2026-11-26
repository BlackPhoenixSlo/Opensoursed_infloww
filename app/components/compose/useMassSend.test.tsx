import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";

import { makeTestQueryClient } from "@/test-utils";

import { initMassForm, type MassForm } from "./massMessageReducer";
import { useMassSend } from "./useMassSend";

const postSpy = vi.fn(async (..._a: unknown[]) => ({}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: (...a: unknown[]) => postSpy(...a) } };
});
vi.mock("@/hooks/useSmartLists", () => ({ resolveSmartLists: vi.fn(async () => []) }));

afterEach(() => postSpy.mockReset());

describe("useMassSend POSTs exactly sendFrom", () => {
  it.each<[string, MassForm, string[]]>([
    ["All-models", { ...initMassForm(), allModels: true, text: "hi" }, ["of1", "of2"]],
    ["All-models retry", { ...initMassForm(), allModels: true, text: "hi",
      results: [{ accountId: "of1", ok: true }] }, ["of2"]],
    ["one account: sendFrom's, not the form's", { ...initMassForm("fs1"), text: "hi" }, ["ofX"]],
  ])("%s", async (_n, form, sendFrom) => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={makeTestQueryClient()}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useMassSend({
      form, dispatch: vi.fn(), online: false, invalid: null, employeeId: 1, onClose: vi.fn(), isEligible: () => true,
    }), { wrapper });
    await act(() => result.current.mutateAsync(sendFrom));
    expect(postSpy.mock.calls.map((c) => (c[2] as { accountId: string }).accountId)).toEqual(sendFrom);
  });
});

it("invalidates the original targets after results shrink the retry set", async () => {
  const client = makeTestQueryClient();
  client.setQueryDefaults(["scheduled"], { gcTime: Infinity });
  client.setQueryDefaults(["mass-messages"], { gcTime: Infinity });
  const keys = [["scheduled", "of1"], ["mass-messages", "of2"], ["scheduled", "other"]];
  keys.forEach((key) => client.setQueryData(key, []));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  let finish!: (value: object) => void;
  postSpy.mockImplementation((_path, _body, ctx) => (
    (ctx as { accountId: string }).accountId === "of2"
      ? new Promise((resolve) => { finish = resolve; })
      : Promise.resolve({})
  ));
  const form = { ...initMassForm(), allModels: true, text: "hi" };
  const { result, rerender } = renderHook(({ draft }) => useMassSend({
    form: draft, dispatch: vi.fn(), online: false, invalid: null, employeeId: 1, onClose: vi.fn(), isEligible: () => true,
  }), { wrapper, initialProps: { draft: form } });

  act(() => result.current.mutate(["of1", "of2"]));
  await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(2));
  rerender({ draft: { ...form, results: [{ accountId: "of1", ok: true }] } });
  await act(async () => finish({}));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(keys.map((key) => client.getQueryState(key)?.isInvalidated)).toEqual([true, true, false]);
});

describe("useMassSend op ids", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={makeTestQueryClient()}>{children}</QueryClientProvider>
  );
  const gifs = ["g0", "g1", "g2"].map((id) => ({ id, title: id })) as MassForm["pickedGifs"];
  const ctxs = () => postSpy.mock.calls.map((c) => c[2] as { opId: string; opPart: number });

  it("main body and each extra GIF share one op, each with its own part", async () => {
    const dispatch = vi.fn();
    const { result } = renderHook(() => useMassSend({
      form: { ...initMassForm("of1"), text: "hi", pickedGifs: gifs }, dispatch, online: false, invalid: null,
      employeeId: 1, onClose: vi.fn(), isEligible: () => true,
    }), { wrapper });
    await act(() => result.current.mutateAsync(["of1"]));
    const op = ctxs()[0].opId;
    expect(op).toMatch(/^[0-9a-f-]{36}$/);
    expect(ctxs()).toEqual([0, 1, 2].map((opPart) => expect.objectContaining({ opId: op, opPart })));
    expect(dispatch).toHaveBeenCalledWith({ type: "opMinted", id: op });
  });

  it.each([
    ["one account", { ...initMassForm("of1"), text: "hi", opId: "op-kept" }, ["of1"]],
    ["All-models", { ...initMassForm(), allModels: true, text: "hi", opId: "op-kept" }, ["of1", "of2"]],
  ])("%s resubmit reuses the minted op", async (_n, form, targets) => {
    const dispatch = vi.fn();
    const { result } = renderHook(() => useMassSend({
      form, dispatch, online: false, invalid: null, employeeId: 1, onClose: vi.fn(), isEligible: () => true,
    }), { wrapper });
    await act(() => result.current.mutateAsync(targets));
    expect(ctxs().map((c) => [c.opId, c.opPart])).toEqual(targets.map(() => ["op-kept", 0]));
    expect(dispatch).not.toHaveBeenCalledWith(expect.objectContaining({ type: "opMinted" }));
  });
});

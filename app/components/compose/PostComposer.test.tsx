/**
 * The Post button is disabled while the form is invalid, and its `title` says
 * why — but a phone has no hover. The footer's error line shows the same
 * reason, dimmer than a send error, and clears once the form is valid.
 *
 * All-models: one free text-only body per INCLUDED model (a price typed
 * before is ignored, its row hidden); a partial failure's retry re-posts only
 * the failed models, and the feed refetches as soon as any model took it.
 * After a partial failure the content is locked (the retry sends the same
 * post), the footer counts every outstanding failure, and Start over unlocks.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { PostComposer } from "@/components/compose/PostComposer";

const postSpy = vi.fn(async (..._a: unknown[]) => ({}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: (...a: unknown[]) => postSpy(...a), get: vi.fn(async () => []) } };
});
vi.mock("@/contexts/ScopeContext", () => {
  const all = { scope: { kind: "all" } };
  return { useScope: () => all };
});
vi.mock("@/hooks/useAccounts", () => {
  const accounts = ["acct1", "acct2", "acct3"].map((id) => ({ id, nickname: id.toUpperCase(), color: "#fff" }));
  return { useActiveAccounts: () => accounts, usePlatformAccounts: () => accounts };
});
vi.mock("@/hooks/useAllModelsInclude", () => {
  // acct3 is un-checked in the shared include set.
  const include = { isIncluded: (id: string) => id !== "acct3", toggle: () => {} };
  return { useAllModelsInclude: () => include };
});
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));

afterEach(() => {
  cleanup();
  postSpy.mockReset();
  postSpy.mockImplementation(async () => ({}));
  vi.restoreAllMocks();
});

const TEXT = "What's on your feed today?";
/** Each relay.post call as [account, body]. */
const posted = () => postSpy.mock.calls.map((c) => [(c[2] as { accountId: string }).accountId, c[1]]);

const REASON = "Add text or media";

describe("PostComposer — why Post is disabled, visible without hover", () => {
  it("an empty draft shows the reason; typing clears it", async () => {
    renderWithProviders(<PostComposer open onClose={() => {}} />);
    const btn = screen.getByRole("button", { name: /^Post$/ });
    await waitFor(() => expect(btn).toHaveProperty("disabled", true));
    expect(btn.getAttribute("title")).toBe(REASON);
    const line = screen.getByText(REASON);
    expect(line.className).toContain("text-fg-dim");
    expect(line.className).not.toContain("text-err");

    fireEvent.change(screen.getByPlaceholderText("What's on your feed today?"), { target: { value: "hello" } });
    await waitFor(() => expect(screen.queryByText(REASON)).toBeNull());
    expect(btn).toHaveProperty("disabled", false);
    expect(btn.getAttribute("title")).toBeNull();
    expect(postSpy).not.toHaveBeenCalled();
  });
});

describe("PostComposer — all-models fan-out", () => {
  function allModelsDraft() {
    const onClose = vi.fn();
    const onSuccess = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<PostComposer open onClose={onClose} onSuccess={onSuccess} />);
    fireEvent.change(screen.getByPlaceholderText(TEXT), { target: { value: " hello all " } });
    // A price typed before all-models: the trap the post used to fall into.
    fireEvent.change(screen.getByPlaceholderText("0 (free)"), { target: { value: "10" } });
    fireEvent.click(screen.getByLabelText(/Post from ALL models/));
    return { onClose, onSuccess, confirmSpy, btn: screen.getByRole("button", { name: /^Post$/ }) };
  }

  it("posts one free text-only body per included model; the excluded one is skipped", async () => {
    const { onClose, onSuccess, confirmSpy, btn } = allModelsDraft();
    expect(screen.queryByPlaceholderText("0 (free)")).toBeNull(); // price row hidden
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(confirmSpy).toHaveBeenCalledWith("Post from 2 models?");
    const free = { text: "hello all", media_files: [], price: 0, posted_at: null };
    expect(posted()).toEqual([["acct1", free], ["acct2", free]]);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("a partial failure's retry re-posts only the failed model", async () => {
    postSpy.mockImplementation(async (...a: unknown[]) => {
      if ((a[2] as { accountId: string }).accountId === "acct2") throw new Error("HTTP 500");
      return {};
    });
    const { onClose, onSuccess, confirmSpy, btn } = allModelsDraft();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("1/2 succeeded")).toBeTruthy());
    expect(posted().map((p) => p[0])).toEqual(["acct1", "acct2"]);
    expect(onClose).not.toHaveBeenCalled();
    expect(onSuccess).toHaveBeenCalledTimes(1); // acct1's post is live: the feed refetches
    // Locked: an edit would reach acct2 only, acct1 keeping the old text.
    // (a disabled <fieldset> disables its controls: `:disabled`, not their own attribute)
    expect(screen.getByPlaceholderText(TEXT).matches(":disabled")).toBe(true);
    expect(screen.getByLabelText(/Post from ALL models/)).toHaveProperty("disabled", true);

    postSpy.mockClear();
    postSpy.mockImplementation(async () => ({}));
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(confirmSpy).toHaveBeenLastCalledWith("Post from 1 model?");
    expect(posted()).toEqual([["acct2", { text: "hello all", media_files: [], price: 0, posted_at: null }]]);
    expect(onSuccess).toHaveBeenCalledTimes(2);
  });

  it("BUG: a retry that fails again: the footer counts all rounds (was: the last round's 0/1)", async () => {
    postSpy.mockImplementation(async (...a: unknown[]) => {
      if ((a[2] as { accountId: string }).accountId === "acct2") throw new Error("HTTP 500");
      return {};
    });
    const { onClose, btn } = allModelsDraft();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("1/2 succeeded")).toBeTruthy());
    fireEvent.click(btn);
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    expect(screen.getByText("1/2 succeeded")).toBeTruthy();
    expect(screen.queryByText("0/1 succeeded")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("BUG: in flight the content is locked and Start over is off (was: editable mid-round)", async () => {
    let release = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    let round = 1;
    postSpy.mockImplementation(async (...a: unknown[]) => {
      const aid = (a[2] as { accountId: string }).accountId;
      if (round === 1 && aid === "acct2") throw new Error("HTTP 500");
      await gate; // round 1's acct1, then the retry's acct2: held in flight
      return {};
    });
    const { onClose, btn } = allModelsDraft();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    // Round 1, acct1's POST in flight, no results yet.
    await waitFor(() => expect(screen.getByText("Posting to 0 / 2…")).toBeTruthy());
    expect(screen.getByPlaceholderText(TEXT).matches(":disabled")).toBe(true);
    expect(screen.getByLabelText(/Post from ALL models/)).toHaveProperty("disabled", true);
    release();
    await waitFor(() => expect(screen.getByText("1/2 succeeded")).toBeTruthy());

    round = 2;
    let release2 = () => {};
    const gate2 = new Promise<void>((r) => { release2 = r; });
    postSpy.mockImplementation(async () => { await gate2; return {}; });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("Posting to 0 / 1…")).toBeTruthy());
    const startOver = screen.getByRole("button", { name: "Start over" });
    expect(startOver).toHaveProperty("disabled", true);
    fireEvent.click(startOver);
    expect(screen.getByText(/^Fan-out results/)).toBeTruthy();
    release2();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("Start over drops the results and unlocks the form; the next Post goes to every model", async () => {
    postSpy.mockImplementation(async (...a: unknown[]) => {
      if ((a[2] as { accountId: string }).accountId === "acct2") throw new Error("HTTP 500");
      return {};
    });
    const { confirmSpy, btn } = allModelsDraft();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start over" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(screen.queryByText(/^Fan-out results/)).toBeNull();
    const ta = screen.getByPlaceholderText(TEXT);
    expect(ta.matches(":disabled")).toBe(false);
    fireEvent.change(ta, { target: { value: "edited" } });
    fireEvent.click(btn);
    expect(confirmSpy).toHaveBeenLastCalledWith("Post from 2 models?");
  });
});

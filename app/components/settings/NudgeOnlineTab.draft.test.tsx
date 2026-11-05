/**
 * NudgeOnlineTab's kept draft (lib/pendingDraft): a tab closed mid-save gets
 * its edits back on reopen until a PUT acks them; the ack drops the stash even
 * after the tab unmounted, unless an edit typed during the PUT replaced it.
 * Drives the real component + react-query; only the relay wire and the account
 * list are faked (as in NudgeOnlineTab.refetch.test.tsx).
 */
import { afterEach, beforeAll, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, notifyManager } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});

const A = "123456789";
const acc = vi.hoisted(() => ({ list: [] as { id: string; nickname: string; has_session: boolean }[] }));
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return { ...mod, useActiveAccounts: () => acc.list };
});

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import { nudgeDraftKey } from "@/hooks/useNudgeConfig";
import { RESTORED_MOVED_NOTE, RESTORED_NOTE } from "@/components/settings/nudgeOnlineReducer";
import { readDraft, stashDraft } from "@/lib/pendingDraft";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const KEY = nudgeDraftKey(A);

type Cfg = { delay_minutes: number; jitter_minutes?: number };
const server: { cfg: Cfg } = { cfg: { delay_minutes: 4, jitter_minutes: 3 } };

function serve() {
  relayGet.mockImplementation(async (path: string) => {
    await new Promise((r) => setTimeout(r, 0));
    if (path.startsWith("/admin/nudge-config")) return { account_id: A, config: { ...server.cfg }, defaults: {} };
    if (path.startsWith("/admin/automation-rules")) return { rules: [] };
    return {};
  });
}

/** The next PUT waits for `settle()`; `ok` false = it fails (nothing stored). */
function holdPut(ok = true) {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  relayPut.mockImplementationOnce(async (_path: string, body: { account_id: string; config: Cfg }) => {
    await gate;
    if (!ok) throw new Error("PUT boom");
    server.cfg = body.config;
    return body;
  });
  return () => act(async () => { release(); });
}

function mount(qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  acc.list = [{ id: A, nickname: `acct-${A}`, has_session: true }];
  const r = render(
    <QueryClientProvider client={qc}>
      <NudgeOnlineTab />
    </QueryClientProvider>,
  );
  return { qc, unmount: r.unmount };
}
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const delay = () => field("Delay (min)");
const jitter = () => field("Jitter (min)");
const saveButton = () => screen.getAllByRole("button", { name: "Create automation" })[0];
const ready = () => waitFor(() => expect(saveButton()).not.toBeDisabled(), { timeout: 5_000 });
const kept = () => readDraft<Cfg>(KEY);

beforeAll(() => { notifyManager.setScheduler((cb) => cb()); });
afterEach(() => {
  cleanup(); vi.resetAllMocks(); localStorage.clear();
  server.cfg = { delay_minutes: 4, jitter_minutes: 3 };
});

describe("NudgeOnlineTab's kept draft", () => {
  it("tab closed mid-PUT: the draft is stashed before the PUT, and the ack drops it after unmount", async () => {
    serve();
    const release = holdPut();
    const { qc, unmount } = mount();
    await ready();

    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(kept()?.draft).toMatchObject({ delay_minutes: 9 });
    expect(kept()?.base).toMatchObject({ delay_minutes: 4 });
    unmount();
    expect(kept()?.draft).toMatchObject({ delay_minutes: 9 });

    await release();
    await waitFor(() => expect(kept()).toBeNull());
    // The cache holds the PUT's echo, never the pre-PUT config, once acked.
    expect(qc.getQueryData<{ config: Cfg }>(["nudge-config", A])?.config.delay_minutes).toBe(9);
  });

  it("an edit typed during the PUT stays after the ack (clear only if equal)", async () => {
    serve();
    const release = holdPut();
    mount();
    await ready();

    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    fireEvent.change(jitter(), { target: { value: "1" } });
    act(() => { window.dispatchEvent(new Event("pagehide")); });
    await release();
    await waitFor(() => expect(server.cfg.delay_minutes).toBe(9));
    expect(kept()?.draft).toMatchObject({ delay_minutes: 9, jitter_minutes: 1 });
  });

  it("edit during the PUT, tab closed, PUT lands: the reopen restores it, not as changed elsewhere", async () => {
    serve();
    const release = holdPut();
    const { unmount } = mount();
    await ready();

    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    fireEvent.change(jitter(), { target: { value: "1" } });
    unmount(); // flushes the edit, on the pre-save base
    expect(kept()?.base).toMatchObject({ delay_minutes: 4 });
    await release();
    await waitFor(() => expect(kept()?.base).toMatchObject({ delay_minutes: 9 }));
    expect(kept()?.draft).toMatchObject({ delay_minutes: 9, jitter_minutes: 1 });

    mount();
    await ready();
    expect([delay().value, jitter().value]).toEqual(["9", "1"]);
    expect(screen.getByText(RESTORED_NOTE)).toBeTruthy();
    expect(screen.queryByText(RESTORED_MOVED_NOTE)).toBeNull();
  });

  it("a failed PUT keeps the draft", async () => {
    serve();
    const release = holdPut(false);
    mount();
    await ready();
    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    await release();
    await waitFor(() => expect(screen.getAllByText("PUT boom").length).toBeGreaterThan(0));
    expect(kept()?.draft).toMatchObject({ delay_minutes: 9 });
  });

  it("reopen: the kept draft is restored with the note; Discard takes the server's config", async () => {
    serve();
    stashDraft(KEY, { draft: { delay_minutes: 9, jitter_minutes: 3, slots: {} }, base: { ...server.cfg }, at: 1 });
    mount();
    await ready();
    expect(delay().value).toBe("9");
    expect(screen.getByText(RESTORED_NOTE)).toBeTruthy();
    expect(screen.queryByText(RESTORED_MOVED_NOTE)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(delay().value).toBe("4");
    expect(screen.queryByText(RESTORED_NOTE)).toBeNull();
    expect(kept()).toBeNull();
  });

  it("Discard is off while the restored draft's Save PUT is in flight", async () => {
    serve();
    stashDraft(KEY, { draft: { delay_minutes: 9, jitter_minutes: 3, slots: {} }, base: { ...server.cfg }, at: 1 });
    const release = holdPut();
    mount();
    await ready();
    const discard = () => screen.getByRole("button", { name: "Discard" });
    expect(discard()).not.toBeDisabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(discard()).toBeDisabled();
    fireEvent.click(discard());
    expect(delay().value).toBe("9");
    await release();
    await waitFor(() => expect(screen.queryByText(RESTORED_NOTE)).toBeNull());
    expect(delay().value).toBe("9");
    await waitFor(() => expect(kept()).toBeNull());
  });

  it("reopen after the server moved off the draft's base: restored + warn, never saved by itself", async () => {
    serve();
    stashDraft(KEY, { draft: { delay_minutes: 9, jitter_minutes: 3, slots: {} },
      base: { delay_minutes: 4, jitter_minutes: 2 }, at: 1 });
    mount();
    await ready();
    expect(delay().value).toBe("9");
    expect(screen.getByText(RESTORED_MOVED_NOTE)).toBeTruthy();
    expect(relayPut).not.toHaveBeenCalled();

    relayPut.mockImplementationOnce(async (_p: string, body: { config: Cfg }) => { server.cfg = body.config; return body; });
    fireEvent.click(saveButton());
    await waitFor(() => expect(screen.getAllByText("Saved.").length).toBeGreaterThan(0));
    expect(screen.queryByText(RESTORED_NOTE)).toBeNull();
    await waitFor(() => expect(kept()).toBeNull());
  });

  it("reopen after the ack was lost (draft = server): no note, the stash goes", async () => {
    server.cfg = { delay_minutes: 9, jitter_minutes: 3 };
    serve();
    stashDraft(KEY, { draft: { delay_minutes: 9, jitter_minutes: 3, slots: {} },
      base: { delay_minutes: 4, jitter_minutes: 3 }, at: 1 });
    mount();
    await ready();
    expect(delay().value).toBe("9");
    expect(screen.queryByText(RESTORED_NOTE)).toBeNull();
    await waitFor(() => expect(kept()).toBeNull());
  });
});

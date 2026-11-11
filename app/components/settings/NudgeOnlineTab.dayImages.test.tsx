/**
 * Nudge online's per-day editor and dropped images, through the whole tab on a mocked relay wire:
 *   • picking a day shows what its empty times inherit, and "Edit for …" makes those lines the day's own;
 *   • an image dropped on a time imports into the vault (batch + status poll), the Save waits for it, and the
 *     saved config carries its vault id in that day's slot;
 *   • the preview sends the picked day.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), uploadForm: vi.fn() },
  };
});

const ACCT = "123456789";
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return { ...mod, useActiveAccounts: () => [{ id: ACCT, nickname: "acct", has_session: true }] };
});

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayUpload = relay.uploadForm as unknown as Mock;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
// The tab keeps an unsaved draft in localStorage (usePendingDraft); one case must not seed the next.
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

const SLOTS = { default: { evening: { text: ["eve {name}", "two"], image: [] } } };
let importDone = false;
function wire() {
  importDone = false;
  relayGet.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/nudge-config")) {
      return { account_id: ACCT, config: { enabled: true, slots: SLOTS }, defaults: {} };
    }
    if (path.startsWith("/admin/automation-rules")) return { rules: [] };
    if (path.startsWith("/api/of/v2/vault/upload/status")) {
      return importDone
        ? { status: "done", items: [{ name: "a.png", status: "done", vault_id: 77, error: null }] }
        : { status: "running", items: [{ name: "a.png", status: "uploading", vault_id: null, error: null }] };
    }
    return {};
  });
  relayUpload.mockResolvedValue({ run_id: "r1" });
  relayPut.mockResolvedValue({ ok: true });
  relayPost.mockResolvedValue({ slot: "evening", name: "Jack", messages: [] });
}

const card = (title: string) => screen.getByText(title).parentElement as HTMLElement;

describe("Nudge online per day", () => {
  it("a day shows inherited lines and Edit makes them its own", async () => {
    wire();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });
    await user.click(await screen.findByRole("radio", { name: "Fri" }));
    const eve = card("Evening (18–21)");
    expect(within(eve).getByText(/Uses Every day's 2 lines/)).toBeTruthy();
    await user.click(within(eve).getByRole("button", { name: "Edit for Fridays" }));
    expect((within(eve).getAllByRole("textbox")[0] as HTMLInputElement).value).toBe("eve {name}");
    await user.click(screen.getByRole("button", { name: /Create automation/ }));
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    const body = relayPut.mock.calls.at(-1)![1] as { config: { slots: Record<string, unknown> } };
    expect(body.config.slots.friday).toEqual({ evening: { text: ["eve {name}", "two"], image: [] } });
  });

  it("a dropped image imports, holds Save, then lands in that day's slot", async () => {
    wire();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });
    await user.click(await screen.findByRole("radio", { name: "Sat" }));
    const file = new File(["x"], "a.png", { type: "image/png" });
    fireEvent.drop(card("Night (21–5)"), { dataTransfer: { files: [file], types: ["Files"] } });

    await waitFor(() => expect(relayUpload).toHaveBeenCalled());
    expect(String(relayUpload.mock.calls[0][0])).toBe("/api/of/v2/vault/upload/batch");
    const save = screen.getByRole("button", { name: /Uploading images/ });
    expect(save).toBeDisabled();

    importDone = true;
    await waitFor(() => expect(screen.getByRole("button", { name: /Create automation/ })).not.toBeDisabled(),
      { timeout: 5000 });
    await user.click(screen.getByRole("button", { name: /Create automation/ }));
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    const body = relayPut.mock.calls.at(-1)![1] as { config: { slots: Record<string, unknown> } };
    expect(body.config.slots.saturday).toEqual({ night: { text: [], image: [77] } });
    expect(body.config.slots.default).toEqual(SLOTS.default);
  }, 10000);

  it("a status-poll blip is retried, not a failed upload", async () => {
    wire();
    const base = relayGet.getMockImplementation()!;
    let blips = 2;
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/of/v2/vault/upload/status") && blips-- > 0) throw new Error("network");
      return base(path);
    });
    importDone = true;
    render(<NudgeOnlineTab />, { wrapper });
    const file = new File(["x"], "a.png", { type: "image/png" });
    fireEvent.drop(card(await screen.findByText("Night (21–5)").then((n) => n.textContent!)),
      { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => expect(screen.getByRole("button", { name: /Create automation/ })).not.toBeDisabled(),
      { timeout: 9000 });
    expect(screen.queryByText(/network/)).toBeNull();
    expect(within(card("Night (21–5)")).getAllByRole("button", { name: "Remove image" })).toHaveLength(1);
  }, 12000);

  it("a spinning chip can be let go: Save frees up and its landing is ignored", async () => {
    wire();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });
    const file = new File(["x"], "a.png", { type: "image/png" });
    fireEvent.drop(card(await screen.findByText("Night (21–5)").then((n) => n.textContent!)),
      { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => expect(relayUpload).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Stop waiting for this upload" }));
    expect(screen.getByRole("button", { name: /Create automation/ })).not.toBeDisabled();
    importDone = true;
    await new Promise((r) => setTimeout(r, 2500));
    expect(within(card("Night (21–5)")).queryAllByRole("button", { name: "Remove image" })).toHaveLength(0);
  }, 10000);

  it("a non-image drop uploads nothing", async () => {
    wire();
    render(<NudgeOnlineTab />, { wrapper });
    const night = await screen.findByText("Night (21–5)");
    const file = new File(["x"], "a.txt", { type: "text/plain" });
    fireEvent.drop(night.parentElement!, { dataTransfer: { files: [file], types: ["Files"] } });
    await new Promise((r) => setTimeout(r, 50));
    expect(relayUpload).not.toHaveBeenCalled();
  });

  it("the preview sends the picked day", async () => {
    wire();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });
    await user.selectOptions(await screen.findByRole("combobox", { name: "Day" }), "friday");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalled());
    expect(relayPost.mock.calls.at(-1)![1]).toMatchObject({ weekday: "friday" });
  });
});

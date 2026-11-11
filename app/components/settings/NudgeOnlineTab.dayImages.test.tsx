/**
 * Nudge online's per-day editor and Share, through the whole tab on a mocked relay wire:
 *   • picking a day shows what its empty times inherit, and "Edit for …" makes those lines the day's own;
 *   • images come only from the vault (no upload / drop);
 *   • Share saves this model's unsaved edits, then sends the config to the picked models (none by default);
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
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});

const ACCT = "123456789";
const OTHER = "987654321";
const accts = vi.hoisted(() => ({ list: [] as { id: string; nickname: string; has_session: boolean }[] }));
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return { ...mod, useActiveAccounts: () => accts.list };
});

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
// The tab keeps an unsaved draft in localStorage (usePendingDraft); one case must not seed the next.
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

const SLOTS = { default: { evening: { text: ["eve {name}", "two"], image: [] } } };
function wire(models = [ACCT]) {
  accts.list = models.map((id) => ({ id, nickname: id === ACCT ? "acct" : "other", has_session: true }));
  relayGet.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/nudge-config")) {
      return { account_id: ACCT, config: { enabled: true, slots: SLOTS }, defaults: {} };
    }
    if (path.startsWith("/admin/automation-rules")) return { rules: [] };
    return {};
  });
  relayPut.mockImplementation(async (path: string, body: { config: unknown; account_ids?: string[] }) =>
    path.endsWith("/bulk") ? { applied: [], count: body.account_ids!.length, enabled: true } : { account_id: ACCT, config: body.config });
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

  it("images come from the vault only: no upload button, no drop target", async () => {
    wire();
    render(<NudgeOnlineTab />, { wrapper });
    const night = card(await screen.findByText("Night (21–5)").then((n) => n.textContent!));
    expect(within(night).getByRole("button", { name: "Add image from vault" })).toBeTruthy();
    expect(within(night).queryByRole("button", { name: /Upload/ })).toBeNull();
    fireEvent.drop(night, { dataTransfer: { files: [new File(["x"], "a.png", { type: "image/png" })], types: ["Files"] } });
    expect(within(night).queryByText(/Drop to add/)).toBeNull();
  });

  it("Share: none picked by default; saves this model's edits first, then shares to the picked one", async () => {
    wire([ACCT, OTHER]);
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });
    const btn = await screen.findByRole("button", { name: "Share to 0 models" });
    expect(btn).toBeDisabled();
    // The model being edited is not in its own share list.
    expect(screen.queryByRole("switch", { name: "acct" })).toBeNull();
    await user.click(screen.getByRole("switch", { name: "other" }));
    const eve = card("Evening (18–21)");
    await user.clear(within(eve).getAllByRole("textbox")[0]);
    await user.type(within(eve).getAllByRole("textbox")[0], "edited");
    await user.click(screen.getByRole("button", { name: "Share to 1 model" }));
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(2));
    const [[savePath, saveBody], [bulkPath, bulkBody]] = relayPut.mock.calls as [string, Record<string, unknown>][];
    expect(savePath).toBe("/admin/nudge-config");
    expect(saveBody.account_id).toBe(ACCT);
    expect(bulkPath).toBe("/admin/nudge-config/bulk");
    expect(bulkBody).toEqual({ account_ids: [OTHER], config: saveBody.config });
    expect((bulkBody.config as { slots: { default: { evening: { text: string[] } } } }).slots.default.evening.text[0])
      .toBe("edited");
    expect(await screen.findByText(/Shared to 1 model \(on\); each kept its own images/)).toBeTruthy();
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

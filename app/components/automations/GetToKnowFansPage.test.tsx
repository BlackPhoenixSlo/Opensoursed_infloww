/**
 * My Automations › Get to know fans: the header switch is there, and the Model info box opens on the
 * relay's prewritten template while the account has no note (its untouched label lines never reach a
 * prompt: service/tests/test_bio_consistency.py), but on the stored note once there is one. Save sends
 * the stored brain back with only `model_notes` changed. A Human style box toggled while the style save is in
 * flight survives its success (and the next Save sends it); a cutoff typed while the rule PATCH is in flight keeps
 * "Saved" off once it lands.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), uploadFile: vi.fn() },
  };
});
vi.mock("@/components/automations/automationPage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/automations/automationPage")>()),
  useAutomationCreator: () => ({ accountId: ACC, picker: null, loading: false }),
}));

import GetToKnowFansPage from "@/components/automations/GetToKnowFansPage";
import { relay } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const ACC = "8000186";
const TEMPLATE = "Name: \nAge: \nFrom: ";
const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPatch = relay.patch as unknown as Mock;
const KIND = "welcome_chatter_for_info";
const RULE = { id: 7, account_id: ACC, name: "Get to know fans", kind: KIND, is_enabled: true, every_seconds: 300,
  trigger: null, payload: {}, quiet_hours: null, created_at: null, last_run: null, next_due_at: null,
  has_pending_job: false };
const STYLE_ON = { [KIND]: true, [`typos_${KIND}`]: true, [`nonnative_${KIND}`]: true, [`nonnative_spacing_${KIND}`]: true };

const serve = (modelNotes: string | null, withRule = false) =>
  relayGet.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/account-config")) {
      return { account_id: ACC, config: { persona: "Ella.", model_notes: modelNotes }, model_notes_template: TEMPLATE };
    }
    if (path.startsWith("/admin/automation-rules")) return { rules: withRule ? [RULE] : [] };
    if (path.startsWith("/admin/automation-kinds")) {
      return { kinds: withRule ? [{ kind: KIND, label: "Get to know fans", recurring: true, summary: "", knobs: [] }] : [] };
    }
    if (path.startsWith("/admin/style-config")) return { account_id: ACC, config: STYLE_ON, defaults: STYLE_ON };
    return {};
  });

beforeEach(() => {
  relayGet.mockReset();
  relayPut.mockReset();
  relayPut.mockResolvedValue({ account_id: ACC, config: {} });
  relayPatch.mockReset();
  relayPatch.mockResolvedValue(RULE);
});
afterEach(() => cleanup());

describe("Get to know fans", () => {
  it("shows the header switch and prefills the template while there is no note", async () => {
    serve(null);
    renderWithProviders(<GetToKnowFansPage />, makeTestQueryClient());
    expect(await screen.findByRole("switch", { name: "Get to know fans" })).toBeTruthy();
    const box = (await screen.findByRole("textbox", { name: "Model info" })) as HTMLTextAreaElement;
    expect(box.value).toBe(TEMPLATE);

    fireEvent.change(box, { target: { value: "Name: Mia\nAge: \nFrom: " } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" }).at(-1)!);
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    expect(relayPut.mock.calls[0]).toEqual(["/admin/account-config", {
      account_id: ACC, config: { persona: "Ella.", model_notes: "Name: Mia\nAge: \nFrom: " },
    }]);
  });

  it("opens on the stored note, not the template", async () => {
    serve("Name: Mia");
    renderWithProviders(<GetToKnowFansPage />, makeTestQueryClient());
    const box = (await screen.findByRole("textbox", { name: "Model info" })) as HTMLTextAreaElement;
    expect(box.value).toBe("Name: Mia");
  });

  it("keeps a style box toggled while the style save is in flight", async () => {
    serve("Name: Mia", true);
    let land!: (v: unknown) => void;
    relayPut.mockImplementation((path: string) => path === "/admin/style-config"
      ? new Promise((res) => { land = res; })
      : Promise.resolve({ account_id: ACC, config: {} }));
    renderWithProviders(<GetToKnowFansPage />, makeTestQueryClient());

    fireEvent.click(await screen.findByRole("switch", { name: /Realistic typos/ }));
    const save = screen.getAllByRole("button", { name: "Save" })[0];
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("switch", { name: /Human style/ }));   // while the PUT is out
    land({ account_id: ACC, config: { [`typos_${KIND}`]: false } });
    await waitFor(() => expect(save).not.toBeDisabled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("switch", { name: /Human style/ })).not.toBeChecked();
    expect(screen.queryByText("Saved")).toBeNull();   // the in-flight toggle is not saved yet

    relayPut.mockResolvedValue({ account_id: ACC, config: {} });
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(2));
    expect(relayPut.mock.calls[1]).toEqual(["/admin/style-config", { account_id: ACC, config: { [KIND]: false } }]);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("does not show Saved over a cutoff typed while the rule save was in flight", async () => {
    serve("Name: Mia", true);
    let land!: (v: unknown) => void;
    relayPatch.mockImplementation(() => new Promise((res) => { land = res; }));
    renderWithProviders(<GetToKnowFansPage />, makeTestQueryClient());

    const cutoff = await screen.findByRole("spinbutton", { name: "Message cutoff" });
    const save = screen.getAllByRole("button", { name: "Save" })[0];
    fireEvent.click(save);
    await waitFor(() => expect(relayPatch).toHaveBeenCalledTimes(1));
    fireEvent.change(cutoff, { target: { value: "12" } });   // while the PATCH is out
    land(RULE);
    await waitFor(() => expect(save).not.toBeDisabled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Saved")).toBeNull();

    relayPatch.mockResolvedValue(RULE);
    fireEvent.click(save);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(relayPatch.mock.calls[1][1].payload.max_fan_messages).toBe(12);
  });
});

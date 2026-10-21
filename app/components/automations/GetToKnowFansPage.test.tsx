/**
 * My Automations › Get to know fans: the header switch is there, and the Model info box opens on the
 * relay's prewritten template while the account has no note (its untouched label lines never reach a
 * prompt: service/tests/test_bio_consistency.py), but on the stored note once there is one. Save sends
 * the stored brain back with only `model_notes` changed.
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

const serve = (modelNotes: string | null) =>
  relayGet.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/account-config")) {
      return { account_id: ACC, config: { persona: "Ella.", model_notes: modelNotes }, model_notes_template: TEMPLATE };
    }
    if (path.startsWith("/admin/automation-rules")) return { rules: [] };
    if (path.startsWith("/admin/automation-kinds")) return { kinds: [] };
    return {};
  });

beforeEach(() => {
  relayGet.mockReset();
  relayPut.mockReset();
  relayPut.mockResolvedValue({ account_id: ACC, config: {} });
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
});

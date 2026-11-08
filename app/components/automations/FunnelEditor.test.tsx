/**
 * My Automations > Auto Funnel: `AutoFunnelPage` over `MassFunnelsTab` on
 * Infloww's legacy list page (page-parity ticket 16). Rendered with
 * `@/lib/relay` mocked over one Creator. What is pinned: Learn and "New funnel"
 * in the page header, the "Reply walking" row as a switch that creates the
 * walker rule, the funnels as a table, the editor as a dialog, and Delete
 * through a dialog, never `window.confirm`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return {
    ...mod,
    useActiveAccounts: () => [{ id: "acc-a", nickname: "Creator A", has_session: true }],
    useAccounts: () => ({ isLoading: false }),
  };
});

// The Media pane's vault picker needs the user context; its slots are what's pinned here.
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));
// The Start panel reads the signed-in employee.
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 1 } }) }));

import AutoFunnelPage from "@/components/automations/AutoFunnelPage";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const del = relay.delete as unknown as Mock;
const put = relay.put as unknown as Mock;

/** Funnel 1 as stored: ids with a gap, step 1 routes to step 7. */
const GAPPED = {
  id: 1, name: "strokes", description: "the default", opening_message: "hey", step_count: 2,
  steps: [{ step: 1, messages: ["a"], next: { default: 7 } }, { step: 7, type: "paid_ppv", price: 9, messages: ["b"] }],
};

beforeEach(() => {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/funnels/1/media/")) return Promise.resolve({ opening_media_ids: [], steps_media: {} });
    if (path.startsWith("/admin/funnels/1")) return Promise.resolve(GAPPED);
    if (path.startsWith("/admin/funnels")) {
      return Promise.resolve({ funnels: [
        { id: 1, name: "strokes", description: "the default", opening_message: "hey", step_count: 3 },
      ] });
    }
    if (path.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: [] });
    if (path.startsWith("/admin/ai-key-status")) return Promise.resolve({ account_id: "acc-a", items: [], notices: [] });
    return Promise.resolve({});
  });
  post.mockResolvedValue({});
  put.mockResolvedValue({});
  del.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Auto Funnel (MassFunnelsTab)", () => {
  it("puts Learn and New funnel in the header and lists funnels in a table", async () => {
    renderWithProviders(<AutoFunnelPage />);
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto Funnel" })).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Learn" }));
    expect(screen.getByRole("note")).toHaveTextContent(/Funnels are global/);

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["Name", "Steps", "Description", "Actions"]);
    const row = (await within(table).findByText("strokes")).closest("tr")!;
    expect(within(row).getByText("3")).toBeTruthy();
    for (const name of ["Media", "Start", "Edit", "Delete"]) expect(within(row).getByRole("button", { name })).toBeTruthy();

    fireEvent.click(within(bar).getByRole("button", { name: "New funnel" }));
    expect(screen.getByRole("dialog", { name: "New funnel" })).toBeTruthy();
  });

  it("Reply walking is a switch that creates the walker rule", async () => {
    renderWithProviders(<AutoFunnelPage />);
    const sw = await screen.findByRole("switch", { name: "Reply walking" });
    await waitFor(() => expect(sw).not.toBeDisabled());
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/admin/automation-rules",
      expect.objectContaining({ account_id: "acc-a", kind: "reply_mass_funnel", every_seconds: 120, is_enabled: true }),
    ));
  });

  it("Delete asks in a dialog, not window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    renderWithProviders(<AutoFunnelPage />);
    const row = (await screen.findByText("strokes")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: 'Delete funnel "strokes"?' });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/funnels/1"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("raw JSON: a bad step keeps the last valid draft and blocks save; a fixed one saves through toWire, numbers kept", async () => {
    renderWithProviders(<AutoFunnelPage />);
    fireEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: "New funnel" }));
    const dialog = screen.getByRole("dialog", { name: "New funnel" });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    const area = within(dialog).getByPlaceholderText(/opening_message/);
    const typed = () => within(dialog).getByRole("radio", { name: "Typed fields" });
    const create = () => within(dialog).getByRole("button", { name: "Create funnel" });

    fireEvent.change(area, { target: { value: JSON.stringify({ name: "n", opening_message: "o", steps: [{ messages: ["a"] }] }) } });
    fireEvent.change(area, { target: { value: JSON.stringify({ name: "n", opening_message: "o", steps: [{ type: "paid_ppv", price: "9", messages: ["b"] }] }) } });
    expect(within(dialog).getByText("Step 1 price must be a whole number ≥ 0.")).toBeTruthy();
    fireEvent.click(create());
    fireEvent.click(typed());
    expect(within(dialog).getByPlaceholderText(/opening_message/)).toBeTruthy(); // still raw
    expect(post).not.toHaveBeenCalledWith("/admin/funnels", expect.anything());

    fireEvent.change(area, { target: { value: JSON.stringify({ name: "n", opening_message: "o", steps: [
      { step: 1, messages: ["a"], next: { default: 7 } },
      { step: 7, type: "paid_ppv", price: 9, messages: [" b "] },
    ] }) } });
    expect(within(dialog).queryByText(/must be|needs/)).toBeNull();
    fireEvent.click(create());
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/funnels", {
      name: "n", opening_message: "o", description: null, steps: [
        { step: 1, messages: ["a"], next: { default: 7 } },
        { step: 7, type: "paid_ppv", price: 9, messages: ["b"] },
      ],
    }));
  });

  it("raw JSON → typed fields carries the draft over; a failed save shows its error", async () => {
    post.mockRejectedValueOnce(new Error("step[0].next.default → step 9 references no existing step"));
    renderWithProviders(<AutoFunnelPage />);
    fireEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: "New funnel" }));
    const dialog = screen.getByRole("dialog", { name: "New funnel" });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByPlaceholderText(/opening_message/), { target: { value: JSON.stringify({
      name: "n", opening_message: "o", steps: [{ step: 7, type: "paid_ppv", messages: ["b"] }],
    }) } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Typed fields" }));
    expect((dialog.querySelector("#funnel-name") as HTMLInputElement).value).toBe("n");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create funnel" }));
    // Typed save keeps the step number; no price → none sent (server default).
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/funnels", {
      name: "n", opening_message: "o", description: null, steps: [{ step: 7, type: "paid_ppv", messages: ["b"] }],
    }));
    // The server's 0-based `step[0]` + id reads as the step's position.
    expect(await within(dialog).findByText("Step 1 next.default points to a step that does not exist (id 9).")).toBeTruthy();
  });

  const openEdit = async () => {
    renderWithProviders(<AutoFunnelPage />);
    const row = (await screen.findByText("strokes")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: /Edit funnel/ });
    await within(dialog).findByDisplayValue("hey");
    return dialog;
  };
  const savedSteps = () => (put.mock.calls[0][1] as { steps: { step: number }[] }).steps;

  it("edit a gapped funnel in raw JSON: the buffer shows its ids and an edit saves them", async () => {
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    const area = within(dialog).getByPlaceholderText(/opening_message/) as HTMLTextAreaElement;
    expect(JSON.parse(area.value).steps.map((s: { step: number }) => s.step)).toEqual([1, 7]);
    fireEvent.change(area, { target: { value: area.value.replace('"b"', '"b2"') } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(savedSteps()).toEqual([
      { step: 1, messages: ["a"], next: { default: 7 } },
      { step: 7, type: "paid_ppv", price: 9, messages: ["b2"] },
    ]);
  });

  describe("Escape closes only an untouched draft, never mid-save", () => {
    const escape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    it("seeded and untouched (a mode switch included): Escape closes", async () => {
      const dialog = await openEdit();
      fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
      escape();
      expect(screen.queryByRole("dialog", { name: /Edit funnel/ })).toBeNull();
    });
    it("a typed name: Escape does nothing", async () => {
      const dialog = await openEdit();
      fireEvent.change(dialog.querySelector("#funnel-name")!, { target: { value: "x" } });
      escape();
      expect(screen.getByRole("dialog", { name: /Edit funnel/ })).toBeTruthy();
    });
    it("mid-save: Escape does nothing", async () => {
      put.mockImplementationOnce(() => new Promise(() => {}));
      const dialog = await openEdit();
      fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(put).toHaveBeenCalled());
      escape();
      expect(screen.getByRole("dialog", { name: /Edit funnel/ })).toBeTruthy();
    });
  });

  it("typed add on a gapped funnel numbers the new step max + 1 (no collision)", async () => {
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Reply step" }));
    const blanks = within(dialog).getAllByPlaceholderText("Message…").filter((el) => !(el as HTMLInputElement).value);
    fireEvent.change(blanks[0], { target: { value: "c" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(savedSteps().map((s) => s.step)).toEqual([1, 7, 8]);
  });

  it("a reply step's variant pool: typed, added and imported variants save as messages", async () => {
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Reply step" }));
    const first = within(dialog).getAllByPlaceholderText("Message…").filter((el) => !(el as HTMLInputElement).value)[0];
    fireEvent.change(first, { target: { value: "x" } });
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Import captions" }).at(-1)!);
    fireEvent.change(within(dialog).getByLabelText("Paste captions"), { target: { value: "y\nz" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add pasted" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    // The step's static pool is capped at the 2 the walker sends.
    expect(savedSteps()[2]).toEqual({ step: 8, messages: ["x", "y"] });
  });

  it("a server 422 on save names the step by position, not step[i] or its id", async () => {
    put.mockRejectedValueOnce(new Error("step[1].next.bought → step 9 references no existing step"));
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("Step 2 next.bought points to a step that does not exist (id 9).")).toBeTruthy();
    expect(within(dialog).queryByText(/step\[1\]/)).toBeNull();
  });

  it("one panel at a time: Start / Media toggle under the row, Edit and New funnel close them", async () => {
    renderWithProviders(<AutoFunnelPage />);
    const row = (await screen.findByText("strokes")).closest("tr")!;
    const btn = (name: string) => within(row).getByRole("button", { name });
    const expanded = () => [btn("Start"), btn("Media")].map((b) => b.getAttribute("aria-expanded"));
    fireEvent.click(btn("Start"));
    expect(expanded()).toEqual(["true", "false"]);
    fireEvent.click(btn("Media"));
    expect(expanded()).toEqual(["false", "true"]);
    fireEvent.click(btn("Media"));
    expect(expanded()).toEqual(["false", "false"]);
    fireEvent.click(btn("Start"));
    fireEvent.click(btn("Edit"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(expanded()).toEqual(["false", "false"]);
    fireEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: "New funnel" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "New funnel" })).toBeTruthy();
  });

  it("Media labels a PPV step by its position, not its id (id 7 is Step 2)", async () => {
    renderWithProviders(<AutoFunnelPage />);
    const row = (await screen.findByText("strokes")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Media" }));
    expect(await screen.findByText("Step 2 · PPV")).toBeTruthy();
    expect(screen.queryByText("Step 7 · PPV")).toBeNull();
  });
});

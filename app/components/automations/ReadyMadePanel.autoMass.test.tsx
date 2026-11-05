/**
 * My Automations > Auto Mass (/growth/auto-mass) is `ReadyMadePanel` pinned to
 * the `mass_premade` kind. Rendered with `@/lib/relay` mocked over one Creator.
 * What is pinned: the page header (title, the blurb as Learn's popover), no tab
 * strip, only `mass_premade` rules listed, and the header's "New auto mass"
 * opening the editor dialog for that kind.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

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

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;

const rule = (id: number, kind: string, name: string) => ({
  id, account_id: "acc-a", kind, name, every_seconds: 86400, payload: { messages: [{ text: "hi" }] },
  is_enabled: true, next_due_at: null, has_pending_job: false, last_run: null,
});

/** The dialog's enabled primary (IfButton `bg-accent`) buttons: the editor wants exactly one live primary at a time. */
const enabledPrimaries = (dialog: HTMLElement) =>
  within(dialog).getAllByRole("button").filter((b) => b.classList.contains("bg-accent") && !b.hasAttribute("disabled"));

beforeEach(() => {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/automation-rules")) {
      return Promise.resolve({ rules: [rule(1, "mass_premade", "Evening tease"), rule(2, "auto_posts", "Feed")] });
    }
    if (path.startsWith("/admin/stats/automation-runs")) return Promise.resolve({ runs: [] });
    return Promise.resolve({});
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Auto Mass (ReadyMadePanel only=mass_premade)", () => {
  it("is the Auto Mass page: header, Learn's blurb, no tab strip, only mass_premade rules", async () => {
    renderWithProviders(<ReadyMadePanel only="mass_premade" />);
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto Mass" })).toBeTruthy();
    // The creator is picked on the creator column left of the page, not in the header; it shows Creator A.
    expect(within(bar).queryByRole("combobox", { name: "Creator" })).toBeNull();
    const column = screen.getByTestId("of-creator-column");
    expect(bar.compareDocumentPosition(column) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(column).getByRole("button", { name: /Creator A/ })).toHaveAttribute("aria-current", "true");
    fireEvent.click(within(bar).getByRole("button", { name: "Learn" }));
    expect(screen.getByRole("note")).toHaveTextContent(/same OF mass message path as Smart Messages/);

    expect(await screen.findByText("Evening tease")).toBeTruthy();
    expect(column.nextElementSibling!.contains(screen.getByText("Evening tease"))).toBe(true);
    expect(screen.queryByText("Feed")).toBeNull();
    expect(screen.queryByRole("button", { name: /Mass Premade/ })).toBeNull();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("the header's New auto mass opens the auto mass message editor dialog", async () => {
    renderWithProviders(<ReadyMadePanel only="mass_premade" />);
    await screen.findByText("Evening tease");
    fireEvent.click(screen.getByRole("button", { name: "New auto mass" }));
    const dialog = screen.getByRole("dialog", { name: "New auto mass message" });
    expect(within(dialog).getByText("Messages")).toBeTruthy();
    expect(within(dialog).getByRole("switch", { name: "Enabled" })).toHaveAttribute("aria-checked", "true");
    expect(within(dialog).getByRole("combobox", { name: "Interval unit" })).toHaveTextContent("hours");
  });

  it("empty editor: Compose is the one primary, Create waits for this kind's messages and a parseable buffer", async () => {
    renderWithProviders(<ReadyMadePanel only="mass_premade" />);
    await screen.findByText("Evening tease");
    fireEvent.click(screen.getByRole("button", { name: "New auto mass" }));
    const dialog = screen.getByRole("dialog", { name: "New auto mass message" });
    const create = within(dialog).getByRole("button", { name: "Create" });
    const group = within(dialog).getByRole("group", { name: "Messages" });
    const compose = within(group).getByRole("button", { name: "Compose" });
    expect(compose).toHaveClass("bg-accent");
    expect(compose).toHaveAccessibleDescription("Add at least one message to enable Create.");
    expect(create).toBeDisabled();
    expect(enabledPrimaries(dialog)).toEqual([compose]);

    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    const ta = within(dialog).getByRole("textbox", { name: "Messages JSON" });
    const cases: [string, boolean][] = [
      ['{ "posts": [ { "text": "x" } ], "messages": [] }', false], // another kind's list is not content
      ['{ "posts": [], "messages": [ { "text": "Hello" } ] }', true],
      ['{ "messages": [ {', false], // unparseable: the last valid value is kept, Create still waits
    ];
    expect(ta).toHaveAccessibleDescription("Add at least one message to enable Create.");
    for (const [text, enabled] of cases) {
      fireEvent.change(ta, { target: { value: text } });
      expect(create.hasAttribute("disabled"), text).toBe(!enabled);
    }
    expect(within(dialog).queryByText("Add at least one message to enable Create.")).toBeNull(); // last valid value has a message
    fireEvent.change(ta, { target: { value: cases[1][0] } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Composer" }));
    expect(within(dialog).getByText("1 message · Hello")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Edit content" })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Compose" })).toBeNull();
    expect(create).toBeEnabled();
    expect(enabledPrimaries(dialog)).toEqual([create]);
  });

  it("editing a rule: emptied raw JSON names Save changes in the help and disables it", async () => {
    renderWithProviders(<ReadyMadePanel only="mass_premade" />);
    await screen.findByText("Evening tease");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit · Evening tease" });
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    expect(save).toBeEnabled();
    expect(enabledPrimaries(dialog)).toEqual([save]);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Messages JSON" }), { target: { value: '{ "messages": [] }' } });
    expect(save).toBeDisabled();
    expect(within(dialog).getByText("Add at least one message to enable Save changes.")).toBeTruthy();
    expect(enabledPrimaries(dialog)).toEqual([]); // raw view: no Compose, Save waits
  });
});

/**
 * PremadeFields, a ready-made rule's one post / message inline in the rule popup (ReadyMadeRuleEditor). Driven here
 * through a harness that owns the row like the popup's reducer and builds the payload on "Use in rule" (premadeRows
 * `buildPayload`, what Create saves). It has no send path of its own: it imports no relay write.
 */
import { useReducer } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { PremadeFields } from "@/components/compose/PremadeFields";
import { buildPayload, payloadToRow, rowReducer, type PremadePayload } from "@/components/compose/premadeRows";
import { hasContent, type Kind } from "@/components/compose/payloadRules";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(async () => []) } }));
vi.mock("@/contexts/EmployeeContext", () => ({
  useEmployee: () => ({ current: { id: 1 } }),
}));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [{ id: "acct1", nickname: "A", color: "#fff" }],
  usePlatformAccounts: () => [{ id: "acct1", nickname: "A", color: "#fff" }],
}));
vi.mock("@/hooks/useAllModelsInclude", () => ({
  useAllModelsInclude: () => ({ isIncluded: () => true, toggle: vi.fn() }),
}));
vi.mock("@/hooks/useVaultMedia", () => ({
  useVaultLists: () => ({ data: { list: [] }, isLoading: false }),
}));
// The vault picker's last props (it renders a marker while mounted): which pool it opens for, and its confirm.
type PickerProps = {
  open: boolean; initialSelectedIds: number[]; onClose: () => void; onConfirm: (p: { id: number }[]) => void;
};
const picker = vi.hoisted(() => ({ all: [] as PickerProps[] }));
vi.mock("@/components/chat/VaultPicker", () => ({
  VaultPicker: (p: PickerProps) => { picker.all.push(p); return <div data-testid="vault-picker" />; },
}));
const lastPicker = () => picker.all[picker.all.length - 1];

afterEach(() => cleanup());

/** The popup's share of the job: own the row, build the payload (no content → nothing to save). */
function Harness({ kind, onComposePayload, initialPayload }: {
  kind: Kind;
  onComposePayload: (p: PremadePayload) => void;
  initialPayload?: Record<string, unknown>;
}) {
  const [row, dispatch] = useReducer(rowReducer, undefined, () => payloadToRow(initialPayload, kind));
  return (
    <>
      <PremadeFields kind={kind} accountId="acct1" row={row} dispatch={dispatch} />
      <button type="button" onClick={() => { const p = buildPayload(row, kind); if (hasContent(p, kind)) onComposePayload(p); }}>
        Use in rule
      </button>
    </>
  );
}

describe("PremadeFields", () => {
  it("auto_posts: hands back {posts:[…]}", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <Harness
        kind="auto_posts"
        onComposePayload={onComposePayload}
      />,
    );

    // No all-models switch + no enqueue button in return mode.
    expect(screen.queryByText(/from ALL models/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /enqueue/i })).toBeNull();

    fireEvent.change(screen.getByPlaceholderText(/post caption/i), {
      target: { value: "hello world" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));

    expect(onComposePayload).toHaveBeenCalledTimes(1);
    expect(onComposePayload).toHaveBeenCalledWith({ posts: [{ text: "hello world" }] });
  });

  it("auto_posts: a PPV price rides into the {posts:[…]} payload", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <Harness
        kind="auto_posts"
        onComposePayload={onComposePayload}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/post caption/i), {
      target: { value: "locked pic" },
    });
    // The auto_posts-only price field (dollars) → emitted only when >0.
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), {
      target: { value: "19.99" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));

    expect(onComposePayload).toHaveBeenCalledWith({
      posts: [{ text: "locked pic", price: 19.99 }],
    });
  });

  // One clock: the rule's "Run every". One post, no list / repost cycle / delay; preview pool only when paid.
  it("auto_posts: one post, no list or timers; auto-delete and the paid preview pool", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<Harness kind="auto_posts" onComposePayload={onComposePayload} />);
    expect(screen.queryByRole("heading", { name: /Post 1/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Repost cycle" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Add another/ })).toBeNull();
    for (const gone of ["Delay before posting", "Repost whole list after", "Repost this many times"]) {
      expect(screen.queryByLabelText(gone)).toBeNull();
    }
    expect(screen.queryByRole("button", { name: "More settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Pick preview pool" })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/post caption/i), { target: { value: "x" } });
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), { target: { value: "12" } });
    expect(screen.getByRole("button", { name: "Pick preview pool" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Auto-delete after"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenLastCalledWith({ posts: [{ text: "x", price: 12, hours_to_live: 6 }] });
  });

  it("auto_posts re-compose: a saved post fills the form and round-trips", () => {
    const onComposePayload = vi.fn();
    const post = { texts: ["a", "b"], media_folder_id: 4, media_count: 2, price: 5, preview_media_files: [9], hours_to_live: 8 };
    renderWithProviders(<Harness kind="auto_posts"
      onComposePayload={onComposePayload} initialPayload={{ posts: [post] }} />);
    expect(screen.getByLabelText("Auto-delete after")).toHaveValue("8");
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenLastCalledWith({ posts: [post] });
  });

  it("mass_premade: hands back {messages:[…]}, the default audience and online-only included", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <Harness
        kind="mass_premade"
        onComposePayload={onComposePayload}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), {
      target: { value: "premade promo" },
    });
    // Price parity with auto_posts: a PPV broadcast rides `price` too
    // (mass_premade → send_mass_message both read it).
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), {
      target: { value: "9.99" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));

    expect(onComposePayload).toHaveBeenCalledTimes(1);
    expect(onComposePayload).toHaveBeenCalledWith({
      messages: [{
        text: "premade promo", price: 9.99, online_only: true, user_lists: ["fans", "following"], exclude_last_chat_hours: 1,
      }],
    });
  });

  it("mass_premade: a system chip is include-only (OF drops a built-in name in excludedLists)", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<Harness kind="mass_premade" onComposePayload={onComposePayload} />);
    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), { target: { value: "x" } });
    const fans = screen.getByRole("button", { name: /All fans/ });
    fireEvent.click(fans); // included → off
    expect(fans).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(fans); // off → included, never "exclude"
    fireEvent.click(fans);
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledWith({
      messages: [{ text: "x", online_only: true, user_lists: ["following"], exclude_last_chat_hours: 1 }],
    });
  });

  // One clock: the rule's "Run every". One message, no list / resend / delay; one up-front recent-chat guard.
  it("mass_premade: one message, no list or timers; Skip chatted-with chips; More settings collapsed", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<Harness kind="mass_premade" onComposePayload={onComposePayload} />);
    expect(screen.queryByRole("heading", { name: /Message 1/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Add another/ })).toBeNull();
    for (const gone of ["Resend this many times", "Wait between resends", "Delay before posting"]) {
      expect(screen.queryByLabelText(gone)).toBeNull();
    }
    const chips = screen.getByRole("radiogroup", { name: "Skip fans chatted with in last" });
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["Off", "1h", "3h", "8h", "24h"]);
    expect(within(chips).getByRole("radio", { name: "1h" })).toHaveAttribute("aria-checked", "true");
    const more = screen.getByRole("button", { name: "More settings" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Exclude I replied to")).toBeNull();
    fireEvent.click(more);
    fireEvent.change(screen.getByLabelText("Exclude I replied to"), { target: { value: "2" } });

    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), { target: { value: "x" } });
    fireEvent.click(within(chips).getByRole("radio", { name: "8h" }));
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenLastCalledWith({
      messages: [{ text: "x", online_only: true, user_lists: ["fans", "following"], exclude_last_chat_hours: 8, exclude_replied_hours: 2 }],
    });
    fireEvent.click(within(chips).getByRole("radio", { name: "Off" }));
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenLastCalledWith({
      messages: [{ text: "x", online_only: true, user_lists: ["fans", "following"], exclude_replied_hours: 2 }],
    });
  });

  it("mass_premade: replied / inbound guards say their defaults; 0 is sent (guard off)", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<Harness kind="mass_premade" onComposePayload={onComposePayload}
      initialPayload={{ messages: [{ text: "x", user_lists: ["fans"], exclude_replied_hours: 0 }] }} />);
    expect(screen.getByRole("button", { name: "More settings" })).toHaveAttribute("aria-expanded", "true");
    const replied = screen.getByLabelText("Exclude I replied to");
    expect(replied).toHaveValue("0");
    expect(screen.getByText("last N hours · blank = default 6h · 0 = off")).toBeTruthy();
    expect(screen.getByText("last N hours · blank = default 2h · 0 = off")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Exclude who messaged me"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenLastCalledWith({
      messages: [{ text: "x", user_lists: ["fans"], exclude_replied_hours: 0, exclude_inbound_hours: 0 }],
    });
  });

  it.each<[string, Record<string, unknown>, boolean, string]>([
    ["a saved message without the key: Off, More closed", { text: "a" }, false, "Off"],
    ["a More knob opens More", { text: "a", unread_limit: 5, exclude_last_chat_hours: 2 }, true, "2h"],
  ])("mass_premade re-compose: %s", (_name, item, open, checked) => {
    renderWithProviders(<Harness kind="mass_premade" onComposePayload={vi.fn()}
      initialPayload={{ messages: [item] }} />);
    expect(screen.getByRole("button", { name: "More settings" })).toHaveAttribute("aria-expanded", String(open));
    const chips = screen.getByRole("radiogroup", { name: "Skip fans chatted with in last" });
    expect(within(chips).getByRole("radio", { checked: true })).toHaveTextContent(checked);
  });

  it("one vault picker fills the image pool or the preview pool it was opened for", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<Harness kind="auto_posts" onComposePayload={onComposePayload} />);
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), { target: { value: "5" } });
    picker.all = [];
    fireEvent.click(screen.getByRole("button", { name: "Pick image pool" }));
    expect(lastPicker().open).toBe(true);
    act(() => lastPicker().onConfirm([{ id: 1 }, { id: 2 }]));
    expect(screen.queryByTestId("vault-picker")).toBeNull(); // closed = unmounted
    fireEvent.click(screen.getByRole("button", { name: "Pick preview pool" }));
    expect(lastPicker().initialSelectedIds).toEqual([]);
    act(() => lastPicker().onConfirm([{ id: 3 }]));
    fireEvent.click(screen.getByRole("button", { name: "2 in pool" }));
    expect(lastPicker().initialSelectedIds).toEqual([1, 2]);
    act(() => lastPicker().onClose());
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledWith({
      posts: [{ media_files: [1, 2], price: 5, preview_media_files: [3] }],
    });
  });

  it("does nothing (no callback) when there's no content", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <Harness
        kind="auto_posts"
        onComposePayload={onComposePayload}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).not.toHaveBeenCalled();
  });

  it("a saved folder that is gone (none fetched) still shows and clears", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <Harness
        kind="auto_posts"
        onComposePayload={onComposePayload}
        initialPayload={{ posts: [{ text: "hi", media_folder_id: 77 }] }}
      />,
    );
    const folder = screen.getAllByLabelText("Folder pool")[0];
    expect(folder).toBeEnabled();
    expect(folder).toHaveTextContent("Missing folder #77");
    fireEvent.click(folder);
    fireEvent.click(screen.getByRole("option", { name: "No photo folders" }));
    expect(folder).toHaveTextContent("No photo folders");
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledWith({ posts: [{ text: "hi" }] });
  });

  // The text-variant pool: typed, added and imported variants land in `texts` in order (dupes skipped).
  it.each([
    ["auto_posts", /post caption/i, "posts"],
    ["mass_premade", /broadcast text/i, "messages"],
  ] as const)("%s: the variant pool rides as texts", (kind, ph, key) => {
    const onComposePayload = vi.fn();
    const { container } = renderWithProviders(<Harness kind={kind} onComposePayload={onComposePayload} />);
    const first = screen.getByPlaceholderText(ph);
    fireEvent.change(first, { target: { value: " a " } });
    fireEvent.click(screen.getByRole("button", { name: /^Add variant/ }));
    const boxes = [...container.querySelectorAll("textarea")];
    fireEvent.change(boxes[boxes.indexOf(first as HTMLTextAreaElement) + 1], { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: "Import captions" }));
    fireEvent.change(screen.getByLabelText("Paste captions"), { target: { value: "c\nb" } });
    fireEvent.click(screen.getByRole("button", { name: "Add pasted" }));
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledTimes(1);
    expect(onComposePayload.mock.calls[0][0][key][0].texts).toEqual(["a", "b", "c"]);
  });
});

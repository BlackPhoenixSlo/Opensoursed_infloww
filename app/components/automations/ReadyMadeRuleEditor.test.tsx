/**
 * ReadyMadeRuleEditor (Auto Post / Auto Mass create + edit popup), both kinds. What is pinned: the post / message
 * fields sit in the popup itself (no Compose dialog, no "Use in rule"), Create waits on text or media with a help line
 * naming it, an unparseable Raw JSON buffer is described on the textarea (no alert), a failed save is alerted, an
 * older multi-item rule shows a notice + Raw JSON only, and Escape never drops an edit. The state transitions are the
 * pure tables in ruleEditorForm.test.ts.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(async () => []), post: vi.fn() } };
});
vi.mock("@/hooks/useVaultMedia", () => ({
  useVaultLists: () => ({ data: { list: [] }, isLoading: false }),
}));
// The vault picker's last props (it renders nothing).
type PickerProps = { open: boolean; onClose: () => void };
const picker = vi.hoisted(() => ({ all: [] as PickerProps[] }));
vi.mock("@/components/chat/VaultPicker", () => ({
  VaultPicker: (p: PickerProps) => { picker.all.push(p); return null; },
}));

import { ReadyMadeRuleEditor } from "@/components/automations/ReadyMadeRuleEditor";
import type { Kind } from "@/components/compose/premadeRows";
import type { AutomationRule } from "@/hooks/useAutomations";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const post = relay.post as unknown as Mock;

/** The dialog's enabled primaries. No role/attr names IfButton's variant, so this reads its `bg-accent` fill. */
const enabledPrimaries = (dialog: HTMLElement) =>
  within(dialog).getAllByRole("button").filter((b) => b.classList.contains("bg-accent") && !b.hasAttribute("disabled"));

afterEach(() => { cleanup(); post.mockReset(); });

describe.each<[Kind, string, string, string, RegExp, string]>([
  ["auto_posts", "posts", "post", "Post", /post caption/i, "from json"],
  ["mass_premade", "messages", "message", "Message", /broadcast text/i, "from json"],
])("ReadyMadeRuleEditor %s", (kind, key, item, items, placeholder, summary) => {
  const open = (editing: AutomationRule | null = null) => {
    renderWithProviders(<ReadyMadeRuleEditor kind={kind} accountId="acc-a" editing={editing} onClose={() => {}} />);
    return screen.getByRole("dialog");
  };

  it("new: the fields are in the popup; Create waits for text or media", () => {
    const dialog = open();
    const create = within(dialog).getByRole("button", { name: "Create" });
    expect(within(dialog).queryByRole("button", { name: "Compose" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /use in rule/i })).toBeNull();
    expect(within(dialog).queryByRole("dialog")).toBeNull(); // no nested composer
    expect(create).toBeDisabled();
    expect(create).toHaveAccessibleDescription("Add text or media to enable Create.");

    fireEvent.change(within(within(dialog).getByRole("group", { name: items })).getByPlaceholderText(placeholder),
      { target: { value: "Hello" } });
    expect(create).toBeEnabled();
    expect(within(dialog).queryByText("Add text or media to enable Create.")).toBeNull();
    expect(enabledPrimaries(dialog)).toEqual([create]);
  });

  it("Create saves the one-item payload typed in the popup", async () => {
    post.mockResolvedValueOnce({});
    const dialog = open();
    fireEvent.change(within(dialog).getByPlaceholderText(placeholder), { target: { value: "Hello" } });
    fireEvent.change(within(dialog).getByLabelText("Price (USD)"), { target: { value: "12" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [, body] = post.mock.calls[0];
    expect(body).toMatchObject({ account_id: "acc-a", kind, every_seconds: 86400, is_enabled: true });
    expect(body.name).toBe(kind === "auto_posts" ? "Auto post" : "Auto mass"); // the placeholder, not the bare kind
    expect(body.payload[key]).toHaveLength(1);
    expect(body.payload[key][0]).toMatchObject({ text: "Hello", price: 12 });
  });

  it("Raw JSON carries the typed post; back on Composer the fields show the buffer", () => {
    const dialog = open();
    fireEvent.change(within(dialog).getByPlaceholderText(placeholder), { target: { value: "typed" } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    const ta = within(dialog).getByRole("textbox", { name: `${items} JSON` }) as HTMLTextAreaElement;
    expect(JSON.parse(ta.value)[key][0].text).toBe("typed");
    fireEvent.change(ta, { target: { value: `{ "${key}": [ { "text": "${summary}" } ] }` } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Composer" }));
    expect(within(dialog).getByPlaceholderText(placeholder)).toHaveValue(summary);
  });

  it("editing: emptied Raw JSON names Save changes in the help and disables it", () => {
    const rule: AutomationRule = {
      id: 1, account_id: "acc-a", kind, name: "Feed", is_enabled: true, every_seconds: 7200,
      trigger: { every_seconds: 7200 }, payload: { [key]: [{ text: "hi" }] }, quiet_hours: null,
      created_at: "2026-11-01T00:00:00Z", last_run: null, next_due_at: null, has_pending_job: false,
    };
    const dialog = open(rule);
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    expect(enabledPrimaries(dialog)).toEqual([save]);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: `${items} JSON` }), { target: { value: `{ "${key}": [] }` } });
    expect(save).toBeDisabled();
    expect(within(dialog).getByText(`Add at least one ${item} to enable Save changes.`)).toBeTruthy();
    expect(enabledPrimaries(dialog)).toEqual([]); // Save waits
  });

  it("an unparseable buffer marks the textarea invalid and describes it with the parse error, never an alert", () => {
    const dialog = open();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    const ta = within(dialog).getByRole("textbox", { name: `${items} JSON` });
    expect(ta).toHaveAttribute("aria-invalid", "false");
    fireEvent.change(ta, { target: { value: `{ "${key}": [ {` } });
    fireEvent.change(ta, { target: { value: `{ "${key}": [ { "` } }); // a second invalid keystroke: still no alert
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(ta).toHaveAttribute("aria-invalid", "true");
    expect(ta).toHaveAccessibleDescription(new RegExp(`^Add at least one ${item} to enable Create\\. Payload is not valid JSON`));
    expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
  });

  it("a failed save (fail()) is alerted", async () => {
    post.mockRejectedValueOnce(new Error("relay down"));
    const dialog = open();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: `${items} JSON` }), {
      target: { value: `{ "${key}": [ { "text": "Hello" } ] }` },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("relay down");
  });
});

// An older multi-item / resend / delayed rule keeps running; the one-item Composer would drop its timers.
describe.each<[Kind, string, string, [string, Record<string, unknown>][], Record<string, unknown>]>([
  ["mass_premade", "Message", "message", [
    ["two messages", { messages: [{ text: "A" }, { text: "B", delay_minutes: 60 }] }],
    ["one message with resends", { messages: [{ text: "A", resend_count: 2, resend_after_hours: 24 }] }],
  ], { messages: [{ text: "A", price: 12 }] }],
  ["auto_posts", "Post", "post", [
    ["two posts", { posts: [{ text: "A", hours_to_live: 6 }, { text: "B", delay_minutes: 30 }] }],
    ["one post with a repost cycle", { posts: [{ text: "A" }], resend_count: 2, resend_after_hours: 24 }],
    ["one post with a delay", { posts: [{ text: "A", delay_minutes: 30 }] }],
  ], { posts: [{ text: "A", price: 12, hours_to_live: 6 }] }],
])("ReadyMadeRuleEditor %s legacy payload", (kind, items, item, legacyCases, current) => {
  const rule = (payload: Record<string, unknown>): AutomationRule => ({
    id: 2, account_id: "acc-a", kind, name: "Old drip", is_enabled: true, every_seconds: 86400,
    trigger: { every_seconds: 86400 }, payload, quiet_hours: null,
    created_at: "2026-11-01T00:00:00Z", last_run: null, next_due_at: null, has_pending_job: false,
  });
  const open = (payload: Record<string, unknown>) => {
    renderWithProviders(<ReadyMadeRuleEditor kind={kind} accountId="acc-a" editing={rule(payload)} onClose={() => {}} />);
    return screen.getByRole("dialog");
  };

  it.each(legacyCases)("%s: a notice and Edit in Raw JSON, no fields", (_name, payload) => {
    const dialog = open(payload);
    expect(within(dialog).getByText(`Older multi-${item} rule — edit in Raw JSON.`)).toBeTruthy();
    expect(within(dialog).queryByLabelText("Price (USD)")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Edit in Raw JSON" }));
    const ta = within(dialog).getByRole("textbox", { name: `${items} JSON` }) as HTMLTextAreaElement;
    expect(JSON.parse(ta.value)).toEqual(payload);
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("a one-item rule opens its fields filled in", () => {
    const dialog = open(current);
    expect(within(dialog).queryByText(/Older multi-/)).toBeNull();
    expect(within(dialog).getByLabelText("Price (USD)")).toHaveValue("12");
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });
});

describe("the rule popup — Escape never drops an edit", () => {
  const escape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  const open = (onClose: () => void) =>
    renderWithProviders(<ReadyMadeRuleEditor kind="auto_posts" accountId="acc-a" editing={null} onClose={onClose} />);
  it("clean: Escape closes", () => {
    const onClose = vi.fn();
    open(onClose);
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it.each<[string, () => void]>([
    ["a caption", () => fireEvent.change(screen.getByPlaceholderText(/post caption/i), { target: { value: "hello" } })],
    ["an auto-delete edit, reverted", () => {
      const hours = screen.getByLabelText("Auto-delete after");
      fireEvent.change(hours, { target: { value: "24" } });
      fireEvent.change(hours, { target: { value: "" } });
    }],
    ["the name", () => fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } })],
  ])("%s holds Escape (touched until it closes)", (_name, act_) => {
    const onClose = vi.fn();
    open(onClose);
    act_();
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
  it("opening and cancelling the vault picker is no edit: Escape still closes", () => {
    const onClose = vi.fn();
    open(onClose);
    fireEvent.click(screen.getByRole("button", { name: "Pick image pool" }));
    act(() => picker.all[picker.all.length - 1].onClose());
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("Auto Mass audience", () => {
  const rule = (payload: Record<string, unknown>): AutomationRule => ({
    id: 9, account_id: "acc-a", kind: "mass_premade", name: "Audience", is_enabled: true, every_seconds: 3600,
    trigger: { every_seconds: 3600 }, payload, quiet_hours: null,
    created_at: "2026-11-01T00:00:00Z", last_run: null, next_due_at: null, has_pending_job: false,
  });
  it("shows Include / Exclude tabs and opens More settings for a saved advanced field", () => {
    const payload = { messages: [{ text: "hi", excluded_user_lists: ["list-7"] }] };
    renderWithProviders(<ReadyMadeRuleEditor kind="mass_premade" accountId="acc-a" editing={rule(payload)} onClose={() => {}} />);
    const more = screen.getByRole("button", { name: "More settings" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("tab", { name: "Include" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Exclude · 1" }));
    expect(screen.getByRole("tabpanel", { name: "Exclude custom lists" })).toBeTruthy();
    cleanup();
    renderWithProviders(<ReadyMadeRuleEditor kind="mass_premade" accountId="acc-a"
      editing={rule({ messages: [{ text: "hi", excluded_user_lists: ["list-7"], exclude_replied_hours: 2 }] })}
      onClose={() => {}} />);
    expect(screen.getByRole("button", { name: "More settings" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Exclude I replied to")).toHaveValue("2");
  });

  it("maps recipient chips and chat skip to the existing payload fields", async () => {
    post.mockResolvedValueOnce({});
    renderWithProviders(<ReadyMadeRuleEditor kind="mass_premade" accountId="acc-a" editing={null} onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: /Following/ }));
    fireEvent.click(screen.getByRole("button", { name: "Online now" }));
    fireEvent.click(screen.getByRole("radio", { name: "3h" }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1].payload.messages[0]).toMatchObject({
      user_lists: ["fans"], exclude_last_chat_hours: 3,
    });
    expect(post.mock.calls[0][1].payload.messages[0].online_only).toBeUndefined();
  });
});

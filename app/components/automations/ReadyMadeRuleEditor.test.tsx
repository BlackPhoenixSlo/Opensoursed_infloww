/**
 * ReadyMadeRuleEditor (Auto Post / Auto Mass create + edit popup), both kinds. What is pinned: the post / message
 * fields sit in the popup itself (no Compose dialog, no "Use in rule"), Create waits on content (and a mass on an
 * audience) with a help line naming it, an unparseable Raw JSON buffer is described on the textarea (no alert), a
 * failed save is alerted, a payload the form can't hold losslessly shows a notice + Raw JSON only and saves untouched
 * byte for byte, Escape never drops an edit and nothing closes the popup mid-save. The state transitions are the pure
 * tables in ruleEditorForm.test.ts.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(async () => []), post: vi.fn(), patch: vi.fn() } };
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
import { MASS_PPV_ADVICE } from "@/components/automations/readyMadeContent";
import type { Kind } from "@/components/compose/payloadRules";
import type { AutomationRule } from "@/hooks/useAutomations";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const post = relay.post as unknown as Mock;
const patchM = relay.patch as unknown as Mock;

/** The dialog's enabled primaries. No role/attr names IfButton's variant, so this reads its `bg-accent` fill. */
const enabledPrimaries = (dialog: HTMLElement) =>
  within(dialog).getAllByRole("button").filter((b) => b.classList.contains("bg-accent") && !b.hasAttribute("disabled"));

afterEach(() => { cleanup(); post.mockReset(); patchM.mockReset(); });

describe.each<[Kind, string, string, string, RegExp, string, string]>([
  ["auto_posts", "posts", "post", "Post", /post caption/i, "from json", "text or media"],
  ["mass_premade", "messages", "message", "Message", /broadcast text/i, "from json", "text"],
])("ReadyMadeRuleEditor %s", (kind, key, item, items, placeholder, summary, content) => {
  const open = (editing: AutomationRule | null = null) => {
    renderWithProviders(<ReadyMadeRuleEditor kind={kind} accountId="acc-a" editing={editing} onClose={() => {}} />);
    return screen.getByRole("dialog");
  };

  it("new: the fields are in the popup; Create waits for content", () => {
    const dialog = open();
    const create = within(dialog).getByRole("button", { name: "Create" });
    expect(within(dialog).queryByRole("button", { name: "Compose" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /use in rule/i })).toBeNull();
    expect(within(dialog).queryByRole("dialog")).toBeNull(); // no nested composer
    expect(create).toBeDisabled();
    expect(create).toHaveAccessibleDescription(`Add ${content} to enable Create.`);

    fireEvent.change(within(within(dialog).getByRole("group", { name: items })).getByPlaceholderText(placeholder),
      { target: { value: "Hello" } });
    expect(create).toBeEnabled();
    expect(within(dialog).queryByText(`Add ${content} to enable Create.`)).toBeNull();
    expect(enabledPrimaries(dialog)).toEqual([create]);
  });

  it("Create saves the one-item payload typed in the popup", async () => {
    post.mockResolvedValueOnce({});
    const dialog = open();
    fireEvent.change(within(dialog).getByPlaceholderText(placeholder), { target: { value: "Hello" } });
    const create = within(dialog).getByRole("button", { name: "Create" });
    // R8 / D6: a paid post with no image never sends, so Create waits and says why; a paid message only warns.
    fireEvent.change(within(dialog).getByLabelText("Price (USD)"), { target: { value: "12" } });
    if (kind === "auto_posts") {
      expect(create).toBeDisabled();
      expect(create).toHaveAccessibleDescription(
        `A paid ${item} needs an image: add one or a vault folder, or make it free, to enable Create.`);
    } else {
      expect(create).toBeEnabled();
      expect(within(dialog).getByText(MASS_PPV_ADVICE)).toBeTruthy();
    }
    fireEvent.change(within(dialog).getByLabelText("Price (USD)"), { target: { value: "" } });
    fireEvent.click(create);
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [, body] = post.mock.calls[0];
    expect(body).toMatchObject({ account_id: "acc-a", kind, every_seconds: 86400, is_enabled: true });
    expect(body.name).toBe(kind === "auto_posts" ? "Auto post" : "Auto mass"); // the placeholder, not the bare kind
    expect(body.payload[key]).toHaveLength(1);
    expect(body.payload[key][0]).toMatchObject({ text: "Hello" });
    expect(body.payload[key][0].price).toBeUndefined();
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
      trigger: { every_seconds: 7200 }, quiet_hours: null,
      payload: { [key]: [{ text: "hi", ...(kind === "mass_premade" ? { user_lists: ["fans"] } : {}) }] },
      created_at: "2026-11-01T00:00:00Z", last_run: null, next_due_at: null, has_pending_job: false,
    };
    const dialog = open(rule);
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    expect(enabledPrimaries(dialog)).toEqual([save]);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: `${items} JSON` }), { target: { value: `{ "${key}": [] }` } });
    expect(save).toBeDisabled();
    expect(within(dialog).getByText(`Add at least one ${item} with ${content} to enable Save changes.`)).toBeTruthy();
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
    expect(ta).toHaveAccessibleDescription(new RegExp(`^Add at least one ${item} with ${content} to enable Create\\. Payload is not valid JSON`));
    expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
  });

  it("a failed save (fail()) is alerted", async () => {
    post.mockRejectedValueOnce(new Error("relay down"));
    const dialog = open();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: `${items} JSON` }), {
      target: { value: `{ "${key}": [ { "text": "Hello", "user_lists": ["fans"] } ] }` },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("relay down");
  });
});

// A payload the one-item Composer can't hold losslessly keeps running; the fields would drop its timers / other keys.
// The notice says why (readyMadeContent `formHoldNotice`).
const SETTINGS = "Uses settings the Composer can't edit — edit in Raw JSON.";
const fans = { user_lists: ["fans"] };
describe.each<[Kind, string, [string, Record<string, unknown>, string][], Record<string, unknown>]>([
  ["mass_premade", "Message", [
    ["two messages", { messages: [{ text: "A", ...fans }, { text: "B", delay_minutes: 60 }] }, "Older multi-message rule — edit in Raw JSON."],
    ["one message with resends", { messages: [{ text: "A", resend_count: 2, resend_after_hours: 24, ...fans }] },
      "Older rule with a resend or delay timer — edit in Raw JSON."],
    ["one message with excluded fans", { messages: [{ text: "A", ...fans, excluded_users: [5] }] }, SETTINGS],
    ["one message with an online filter", { messages: [{ text: "A", ...fans, filters: { online: 1 } }] }, SETTINGS],
    ["one message with a string media id", { messages: [{ text: "A", media_files: ["42"], price: 9, ...fans }] }, SETTINGS],
  ], { messages: [{ text: "A", price: 12, media_files: [7], ...fans }] }],
  ["auto_posts", "Post", [
    ["two posts", { posts: [{ text: "A", hours_to_live: 6 }, { text: "B", delay_minutes: 30 }] }, "Older multi-post rule — edit in Raw JSON."],
    ["one post with a repost cycle", { posts: [{ text: "A" }], resend_count: 2, resend_after_hours: 24 },
      "Older rule with a repost or delay timer — edit in Raw JSON."],
    ["one post with a delay", { posts: [{ text: "A", delay_minutes: 30 }] }, "Older rule with a repost or delay timer — edit in Raw JSON."],
    ["one post with media claims", { posts: [{ text: "A", media_claims: [{ id: 1 }] }] }, SETTINGS],
  ], { posts: [{ text: "A", price: 12, media_files: [7], hours_to_live: 6 }] }],
])("ReadyMadeRuleEditor %s legacy payload", (kind, items, legacyCases, current) => {
  const rule = (payload: Record<string, unknown>): AutomationRule => ({
    id: 2, account_id: "acc-a", kind, name: "Old drip", is_enabled: true, every_seconds: 86400,
    trigger: { every_seconds: 86400 }, payload, quiet_hours: null,
    created_at: "2026-11-01T00:00:00Z", last_run: null, next_due_at: null, has_pending_job: false,
  });
  const open = (payload: Record<string, unknown>) => {
    renderWithProviders(<ReadyMadeRuleEditor kind={kind} accountId="acc-a" editing={rule(payload)} onClose={() => {}} />);
    return screen.getByRole("dialog");
  };

  it.each(legacyCases)("%s: a notice and Edit in Raw JSON, no fields", (_name, payload, notice) => {
    const dialog = open(payload);
    expect(within(dialog).getByText(notice)).toBeTruthy();
    expect(within(dialog).queryByLabelText("Price (USD)")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Edit in Raw JSON" }));
    const ta = within(dialog).getByRole("textbox", { name: `${items} JSON` }) as HTMLTextAreaElement;
    expect(JSON.parse(ta.value)).toEqual(payload);
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it.each(legacyCases)("%s: Save changes untouched PATCHes the stored payload byte for byte", async (_name, payload) => {
    patchM.mockResolvedValueOnce({});
    const dialog = open(payload);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await vi.waitFor(() => expect(patchM).toHaveBeenCalledTimes(1));
    const [path, body] = patchM.mock.calls[0];
    expect(path).toBe("/admin/automation-rules/2");
    expect(JSON.stringify(body.payload)).toBe(JSON.stringify(payload));
    expect(body.name).toBe("Old drip");
    expect(body.every_seconds).toBeUndefined(); // the stored interval stays
  });

  it("a one-item rule opens its fields filled in", () => {
    const dialog = open(current);
    expect(within(dialog).queryByText(/edit in Raw JSON/)).toBeNull();
    expect(within(dialog).getByLabelText("Price (USD)")).toHaveValue("12");
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });
});

// R7: the legacy view holds a mass to the backend's audience test too, and says why Save waits.
describe("Auto Mass legacy payload that reaches nobody", () => {
  it("untouched it saves (U2: a rename changes nothing it sends); edited, Save changes waits with the reason", () => {
    const editing: AutomationRule = {
      id: 3, account_id: "acc-a", kind: "mass_premade", name: "Old", is_enabled: true, every_seconds: 86400,
      trigger: { every_seconds: 86400 }, payload: { messages: [{ text: "x" }], note: 1 }, quiet_hours: null,
      created_at: "2026-11-01T00:00:00Z", last_run: null, next_due_at: null, has_pending_job: false,
    };
    renderWithProviders(<ReadyMadeRuleEditor kind="mass_premade" accountId="acc-a" editing={editing} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(SETTINGS)).toBeTruthy();
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    expect(save).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Message JSON" }),
      { target: { value: `{ "messages": [ { "text": "y" } ], "note": 1 }` } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Composer" }));
    expect(within(dialog).getByText(SETTINGS)).toBeTruthy();
    expect(save).toBeDisabled();
    expect(save).toHaveAccessibleDescription("Give the message an audience (user_lists, included_users, list_ids, "
      + "filters, recent_chat_hours, unread_limit) to enable Save changes.");
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

  it.each([true, false])("maps recipient chips and chat skip, online only=%s", async (onlineOnly) => {
    post.mockResolvedValueOnce({});
    renderWithProviders(<ReadyMadeRuleEditor kind="mass_premade" accountId="acc-a" editing={null} onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: /Following/ }));
    const online = screen.getByRole("button", { name: "Send to online only" });
    expect(online).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(online);
    expect(online).toHaveAttribute("aria-pressed", "false");
    if (onlineOnly) fireEvent.click(online);
    expect(online).toHaveAttribute("aria-pressed", String(onlineOnly));
    fireEvent.click(screen.getByRole("radio", { name: "3h" }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1].payload.messages[0]).toMatchObject({
      user_lists: ["fans"], exclude_last_chat_hours: 3,
    });
    expect(post.mock.calls[0][1].payload.messages[0].online_only).toBe(onlineOnly ? true : undefined);
  });
});

describe("Auto Mass: a message that reaches nobody can't be saved", () => {
  it("All fans and Following off, no list: Create off with a help line; a custom list or chatted-with turns it on", () => {
    renderWithProviders(<ReadyMadeRuleEditor kind="mass_premade" accountId="acc-a" editing={null} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), { target: { value: "hi" } });
    const create = within(dialog).getByRole("button", { name: "Create" });
    expect(create).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "All fans" }));
    fireEvent.click(screen.getByRole("button", { name: "Following" }));
    expect(create).toBeDisabled();
    // D5: "Send to online only" (on by default) filters an audience, it isn't one.
    expect(create).toHaveAccessibleDescription(
      "Online only filters an audience: pick All fans, Following or a list to enable Create.");
    fireEvent.click(screen.getByRole("button", { name: "Send to online only" }));
    expect(create).toBeDisabled();
    expect(create).toHaveAccessibleDescription(
      "Pick who gets it (All fans, Following, a list, or chatted-with / unread in More settings) to enable Create.");
    fireEvent.click(screen.getByRole("button", { name: "More settings" }));
    fireEvent.change(screen.getByLabelText("Include chatted-with"), { target: { value: "24" } });
    expect(create).toBeEnabled();
  });
});

describe("the rule popup — nothing closes it mid-save", () => {
  it("while saving: no ×, Escape ignored; a failed save lands on the open popup", async () => {
    let reject: (e: Error) => void = () => {};
    post.mockImplementationOnce(() => new Promise((_, rej) => { reject = rej; }));
    const onClose = vi.fn();
    renderWithProviders(<ReadyMadeRuleEditor kind="auto_posts" accountId="acc-a" editing={null} onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/post caption/i), { target: { value: "hello" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await vi.waitFor(() => expect(within(dialog).getByRole("button", { name: "Saving…" })).toBeDisabled());
    expect(within(dialog).queryByRole("button", { name: "Close" })).toBeNull();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await act(async () => reject(new Error("relay down")));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("relay down");
    expect(onClose).not.toHaveBeenCalled();
  });
});

/**
 * ReadyMadeRuleEditor (Auto Post / Auto Mass create + edit dialog), both kinds. What is pinned: the dialog holds one
 * live primary at a time (Compose while empty, Create / Save changes with content), the help line names the button
 * it waits on, an unparseable Raw JSON buffer is described on the textarea (no alert), and a failed save is alerted.
 * Which inputs count as content is the pure table in readyMadeContent.test.ts.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: vi.fn() } };
});

import { ReadyMadeRuleEditor } from "@/components/automations/ReadyMadeRuleEditor";
import type { Kind } from "@/components/compose/premadeRows";
import type { AutomationRule } from "@/hooks/useAutomations";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const post = relay.post as unknown as Mock;

/** The dialog's enabled primaries. No role/attr names IfButton's variant, so this reads its `bg-accent` fill. */
const enabledPrimaries = (dialog: HTMLElement) =>
  within(dialog).getAllByRole("button").filter((b) => b.classList.contains("bg-accent") && !b.hasAttribute("disabled"));

afterEach(cleanup);

describe.each<[Kind, string, string, string]>([
  ["auto_posts", "posts", "post", "Posts"],
  ["mass_premade", "messages", "message", "Messages"],
])("ReadyMadeRuleEditor %s", (kind, key, item, items) => {
  const open = (editing: AutomationRule | null = null) => {
    renderWithProviders(<ReadyMadeRuleEditor kind={kind} accountId="acc-a" editing={editing} onClose={() => {}} />);
    return screen.getByRole("dialog");
  };

  it("empty: Compose is the one primary; content in Raw JSON hands it to Create", () => {
    const dialog = open();
    const create = within(dialog).getByRole("button", { name: "Create" });
    const compose = within(within(dialog).getByRole("group", { name: items })).getByRole("button", { name: "Compose" });
    expect(compose).toHaveAccessibleDescription(`Add at least one ${item} to enable Create.`);
    expect(create).toBeDisabled();
    expect(enabledPrimaries(dialog)).toEqual([compose]);

    fireEvent.click(within(dialog).getByRole("radio", { name: "Raw JSON" }));
    const ta = within(dialog).getByRole("textbox", { name: `${items} JSON` });
    expect(ta).toHaveAccessibleDescription(`Add at least one ${item} to enable Create.`);
    fireEvent.change(ta, { target: { value: `{ "${key}": [ { "text": "Hello" } ] }` } });
    expect(create).toBeEnabled();
    expect(within(dialog).queryByText(`Add at least one ${item} to enable Create.`)).toBeNull();

    fireEvent.click(within(dialog).getByRole("radio", { name: "Composer" }));
    expect(within(dialog).getByText(`1 ${item} · Hello`)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Edit content" })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Compose" })).toBeNull();
    expect(enabledPrimaries(dialog)).toEqual([create]);
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
    expect(enabledPrimaries(dialog)).toEqual([]); // raw view: no Compose, Save waits
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

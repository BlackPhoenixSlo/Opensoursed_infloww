/**
 * TemplateDraftEditor driven by its real host hook (`useSavedReplyEditor`), `@/lib/relay` mocked. Pins the saved
 * reply wire body: edit an existing reply's text and Save → PUT /admin/saved-replies/:id with FREE tiles first,
 * previews kept, script pair and tags carried; a new reply → POST; a relay 4xx shows OF's message.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));

import { TemplateDraftEditor } from "@/components/settings/TemplateDraftEditor";
import { useSavedReplyEditor } from "@/components/settings/TemplatesTab";
import { RelayError, relay, type SavedReply } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;

const REPLY: SavedReply = {
  id: 7, account_id: "acc-a", title: "Hi", text: "old", price: 5, locked_text: true,
  media: [{ id: 11, type: "photo", files: null }, { id: 12, type: "video", files: null }],
  tagged_users: [99], previews: [12], gif_id: "g1", gif_url: "https://gif/1.gif",
  script_id: "flow", script_step: 2, tags: ["warm"], notes: "  note  ",
} as SavedReply;

function Host({ edit }: { edit?: SavedReply }) {
  const ed = useSavedReplyEditor("acc-a");
  return (
    <>
      <button type="button" onClick={() => (edit ? ed.startEditReply(edit) : ed.startNewReply())}>open</button>
      {ed.draft && (
        <TemplateDraftEditor
          draft={ed.draft} setDraft={ed.setDraft} accountId="acc-a"
          saving={ed.saving} saveErr={ed.saveErr} onSave={ed.save}
        />
      )}
    </>
  );
}

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
  get.mockImplementation((path: string) =>
    Promise.resolve(path.startsWith("/admin/sensitive-words") ? { words: [] } : { list: [] }));
  post.mockResolvedValue({});
  put.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function typeText(v: string) {
  fireEvent.change(screen.getByPlaceholderText("Template text"), { target: { value: v } });
}

describe("TemplateDraftEditor", () => {
  it("renders an existing reply and saves the edited text with today's wire body", async () => {
    renderWithProviders(<Host edit={REPLY} />);
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(screen.getByText("Edit saved reply")).toBeTruthy();
    expect(screen.getByPlaceholderText("Template text")).toHaveValue("old");
    expect(screen.getByRole("button", { name: "FREE" })).toBeTruthy(); // tile 12 is a preview

    typeText("  new text  ");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put).toHaveBeenCalledWith("/admin/saved-replies/7", {
      title: "Hi",
      text: "new text",
      price: 5,
      locked_text: true,
      media: [{ id: 12, type: "video", files: null }, { id: 11, type: "photo", files: null }],
      tagged_users: [99],
      previews: [12],
      gif_id: "g1",
      gif_url: "https://gif/1.gif",
      script_id: "flow",
      script_step: 2,
      tags: ["warm"],
      notes: "note",
    });
    expect(post).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText("Edit saved reply")).toBeNull()); // draft closes
  });

  it("a new reply: Save disabled until text, then POSTs the empty-field defaults", async () => {
    renderWithProviders(<Host />);
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(screen.getByText("New saved reply")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    typeText("hello");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/admin/saved-replies?account_id=acc-a", {
      title: null, text: "hello", price: 0, locked_text: false, media: [], tagged_users: [], previews: [],
      gif_id: null, gif_url: null, script_id: null, script_step: null, tags: [], notes: "",
    });
  });

  it("a failed save shows OF's message from the relay error", async () => {
    post.mockRejectedValue(new RelayError(400, {
      detail: { upstream_body: JSON.stringify({ error: { message: "Text is too long" } }) },
    }, "bad"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    renderWithProviders(<Host />);
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    typeText("hello");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Save failed: Text is too long/)).toBeTruthy();
  });
});

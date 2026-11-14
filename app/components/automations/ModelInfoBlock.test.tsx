import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

import { ModelInfoBlock } from "@/components/automations/ModelInfoBlock";
import { relay } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const ACC = "8000186";
const TEMPLATE = "Name: \nAge: \nFrom: \nPersonality: \nLikes: \nWon't do (hard limits): ";
const DRAFTED = "Name: Kay\nAge: 19\nFrom: Austin, TX\nLooks: blonde, freckles\nPersonality: \nLikes: \nWon't do (hard limits): ";
const BUTTON = "Make persona from the Creator's images";
const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const resp = (over: Record<string, unknown> = {}) => ({
  text: DRAFTED, age: 19, city: "Austin, TX", name: "Kay", images_used: 3, images_described: 0,
  need_describe: false, notes: [], ...over,
});

beforeEach(() => {
  relayGet.mockReset();
  relayGet.mockResolvedValue({ account_id: ACC, config: { persona: "Ella.", model_notes: null }, model_notes_template: TEMPLATE });
  relayPut.mockReset();
  relayPost.mockReset();
});
afterEach(() => cleanup());

const box = async () => (await screen.findByRole("textbox", { name: "Model info" })) as HTMLTextAreaElement;

describe("ModelInfoBlock › Make persona from the Creator's images", () => {
  it("has no button without the prop (Get to know fans, Auto-reply)", async () => {
    renderWithProviders(<ModelInfoBlock accountId={ACC} />, makeTestQueryClient());
    expect((await box()).value).toBe(TEMPLATE);
    expect(screen.queryByRole("button", { name: BUTTON })).toBeNull();
  });

  it("with the prop: one click POSTs the unsaved text and fills the box without saving", async () => {
    relayPost.mockResolvedValue(resp());
    renderWithProviders(<ModelInfoBlock accountId={ACC} draftFromImages />, makeTestQueryClient());
    await box();
    const btn = screen.getByRole("button", { name: BUTTON });
    fireEvent.click(btn);
    fireEvent.click(btn);  // a double tap is one request
    await waitFor(async () => expect((await box()).value).toBe(DRAFTED));
    expect(relayPost).toHaveBeenCalledTimes(1);
    expect(relayPost.mock.calls[0]).toEqual(["/admin/full-ai/persona/draft", { account_id: ACC, current_text: TEMPLATE },
      { accountId: ACC }]);
    expect(relayPut).not.toHaveBeenCalled();
  });

  it("a failed draft keeps the text and shows why", async () => {
    relayPost.mockRejectedValue(new Error("The AI provider failed. Try again."));
    renderWithProviders(<ModelInfoBlock accountId={ACC} draftFromImages />, makeTestQueryClient());
    await box();
    fireEvent.click(screen.getByRole("button", { name: BUTTON }));
    expect(await screen.findByText("The AI provider failed. Try again.")).toBeTruthy();
    expect((await box()).value).toBe(TEMPLATE);
  });

  it("need_describe keeps the text and says what to run", async () => {
    relayPost.mockResolvedValue(resp({ text: "", need_describe: true, images_used: 0 }));
    renderWithProviders(<ModelInfoBlock accountId={ACC} draftFromImages />, makeTestQueryClient());
    await box();
    fireEvent.click(screen.getByRole("button", { name: BUTTON }));
    expect(await screen.findByText("No described images yet. Run Prepare content or the vault describe first.")).toBeTruthy();
    expect((await box()).value).toBe(TEMPLATE);
  });
});

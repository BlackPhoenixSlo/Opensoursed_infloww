/**
 * The answer renderer (AnswerText) is a lazy chunk. Until it lands — or when
 * it never does — an answer is still on screen, as plain text, never a blank
 * bubble. Its own file: the chunk here never resolves.
 */
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayPost } = vi.hoisted(() => ({ relayPost: vi.fn() }));

vi.mock("./AnswerText", () => new Promise(() => {}));
vi.mock("@/lib/relay", () => ({
  RelayError: class extends Error {},
  relay: {
    post: (...a: unknown[]) => relayPost(...a),
    get: () => Promise.resolve({ count: 0, since_hours: 24, list: [], turns: [] }),
  },
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [] }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";

describe("AssistantWidget without its answer renderer", () => {
  it("shows the answer and the connect hint as plain text", async () => {
    relayPost.mockResolvedValue({ answer: "Growth → **Auto Post**.", error: null, id: 1 });
    renderWithProviders(<AssistantProvider><AssistantWidget /></AssistantProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
    expect(screen.getByText(/No account connected yet/)).toBeTruthy();
    await userEvent.type(screen.getByPlaceholderText("Ask a question…"), "autopost?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByText("Growth → **Auto Post**.")).toBeTruthy());
  });
});

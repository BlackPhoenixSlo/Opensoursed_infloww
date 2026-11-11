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
vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: () => {} }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));
const OWNED = { data: { accounts: [] }, isSuccess: true, dataUpdatedAt: 1 };
vi.mock("@/hooks/useAccounts", () => ({ useAccounts: () => OWNED }));
// An owner: the "Add creator" connect hint is theirs.
vi.mock("@/contexts/UserContext", () => ({ useOptionalUser: () => ({ user: { username: "owner" } }) }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";
import { PageCreatorProvider } from "@/contexts/PageCreatorContext";

describe("AssistantWidget without its answer renderer", () => {
  it("shows the answer and the connect hint as plain text", async () => {
    relayPost.mockResolvedValue({ answer: "Growth → **Auto Post**.", error: null, id: 1 });
    renderWithProviders(<PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
    expect(screen.getByText(/No account connected yet/)).toBeTruthy();
    await userEvent.type(screen.getByPlaceholderText("Ask a question…"), "autopost?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByText("Growth → **Auto Post**.")).toBeTruthy());
  });
});

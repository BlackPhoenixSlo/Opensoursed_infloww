/**
 * UnsendMessageButton hides itself once the session's role denies the Unsend messages Function permission
 * (any `<page>#unsend` in the Applied settings' `denied_actions`); the Relay refuses the unsend either way.
 */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

let denied: string[] | undefined;
vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({ data: { permissions: { denied_actions: denied } } }),
}));
vi.mock("@/hooks/useUnsendMessage", () => ({ useUnsendMessage: () => ({ unsendOne: vi.fn() }) }));

import UnsendMessageButton from "@/components/messages/UnsendMessageButton";
import type { PaidMessageRow } from "@/hooks/usePaidMessages";

const ROW = { account_id: "7", fan_id: 9, message_id: 123, sent_at: new Date().toISOString() } as PaidMessageRow;
const renderButton = () =>
  render(<QueryClientProvider client={new QueryClient()}><UnsendMessageButton row={ROW} /></QueryClientProvider>);

describe("UnsendMessageButton", () => {
  it("shows unless the role denies Unsend messages under any page", () => {
    denied = ["/messages-pro#export"];
    renderButton();
    expect(screen.getByRole("button", { name: "Unsend" })).toBeInTheDocument();
    denied = ["/of-manager/messages#unsend"];
    renderButton();
    expect(screen.getAllByRole("button", { name: "Unsend" })).toHaveLength(1);
  });
});

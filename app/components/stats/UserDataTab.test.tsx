import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});


import UserDataTab from "@/components/stats/UserDataTab";
import { relay } from "@/lib/relay";

afterEach(() => cleanup());

describe("UserDataTab labels", () => {
  it("titles the Fan data panel Inflowwww extra", () => {
    (relay.get as unknown as Mock).mockResolvedValue({ accounts: [], rows: [] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><UserDataTab accountId="7" /></QueryClientProvider>);
    const heading = screen.getByRole("heading", { name: "User data" });
    expect(heading.closest("[title]")?.getAttribute("title")).toBe("Inflowwww extra");
  });
});

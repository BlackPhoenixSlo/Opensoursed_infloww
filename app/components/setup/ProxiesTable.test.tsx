/**
 * ProxiesTable — "Paste proxies": the whole textarea goes to
 * POST /admin/proxies/bulk with the chosen scheme, the result shows how many
 * landed plus a row per rejected line, and the table refetches.
 * Contract: docs/proxies.md (Paste many at once).
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), delete: vi.fn(), post: vi.fn() } }));

import ProxiesTable from "@/components/setup/ProxiesTable";
import { relay } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  relayGet.mockReset();
  relayPost.mockReset();
  relayDelete.mockReset();
  relayGet.mockResolvedValue({ proxies: [], pool: { size: 0, account_ids: [] }, accounts: [] });
});
afterEach(() => { cleanup(); });

describe("ProxiesTable paste proxies", () => {
  it("posts the text and scheme, shows Added N and per-line errors, refreshes the table", async () => {
    const text = "u:secret@1.1.1.1:8000\n2.2.2.2:9000:u:secret\nnot a proxy";
    relayPost.mockResolvedValue({
      added: [
        { label: "1.1.1.1:8000", host: "1.1.1.1", port: 8000, scheme: "socks5", username: "u" },
        { label: "2.2.2.2:9000", host: "2.2.2.2", port: 9000, scheme: "socks5", username: "u" },
      ],
      errors: [{ line: 3, text_redacted: "not a proxy", reason: "unrecognised format" }],
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(<ProxiesTable />, { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/proxies"));
    // The paste box sits in the Add new proxy modal (ticket 18).
    fireEvent.click(screen.getByRole("button", { name: "+ Add new proxy" }));
    // page-parity 03: antd dark's modal (#1f1f1f) and fields (#141414 in a 1px #424242 border).
    expect(screen.getByRole("dialog", { name: "Add new proxy" })).toHaveClass("bg-[#1f1f1f]");
    expect(screen.getByLabelText("Paste proxies (one per line)")).toHaveClass("bg-[#141414]", "border-[#424242]");

    fireEvent.change(screen.getByLabelText("Paste proxies (one per line)"), { target: { value: text } });
    fireEvent.change(screen.getByLabelText("Scheme"), { target: { value: "socks5" } });
    fireEvent.click(screen.getByRole("button", { name: "Add all" }));

    await waitFor(() => expect(screen.getByText(/Added 2/)).toBeInTheDocument());
    expect(relayPost).toHaveBeenCalledWith("/admin/proxies/bulk", { text, scheme: "socks5" });
    expect(screen.getByText(/1\.1\.1\.1:8000, 2\.2\.2\.2:9000/)).toBeInTheDocument();
    expect(screen.getByText(/Line 3: unrecognised format/)).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["proxies"] });
    // The pasted text (with passwords) never became a cache key or mutation variable.
    for (const m of client.getMutationCache().getAll()) {
      expect(JSON.stringify(m.state.variables ?? null)).not.toContain("secret");
    }
  });
});

describe("ProxiesTable delete of a proxy in use", () => {
  it("shows the Relay's 409 message naming the Creators that use it", async () => {
    relayGet.mockResolvedValue({
      proxies: [{ label: "hu-1", host: "p.invalid", port: 8080, scheme: "http", assigned_accounts: [] }],
      pool: { size: 0, account_ids: [] },
      accounts: [],
    });
    // relay.ts puts a string `detail` in the error's message.
    relayDelete.mockRejectedValue(Object.assign(new Error("Proxy already in use by Jade. Unbind it first."), { status: 409 }));
    render(<ProxiesTable />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Proxy already in use by Jade. Unbind it first.");
    expect(relayDelete).toHaveBeenCalledWith("/admin/proxies/hu-1");
    // The stale list is refetched.
    await waitFor(() => expect(relayGet.mock.calls.filter(([p]) => p === "/admin/proxies").length).toBeGreaterThan(1));
  });
});

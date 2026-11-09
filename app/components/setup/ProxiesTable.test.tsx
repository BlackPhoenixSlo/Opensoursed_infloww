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
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), delete: vi.fn(), post: vi.fn() } }));

import ProxiesTable, { pagerItems } from "@/components/setup/ProxiesTable";
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
    fireEvent.click(screen.getByRole("button", { name: "Add new proxy" }));
    // page-parity 03: antd dark's modal (#1f1f1f); the kit's field box (IF_FIELD).
    expect(screen.getByRole("dialog", { name: "Add new proxy" })).toHaveClass("bg-[#1f1f1f]");
    expect(screen.getByLabelText("Paste proxies (one per line)")).toHaveClass("bg-bg", "border-border");

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

describe("ProxiesTable Add new proxy modal", () => {
  it("says a taken label under Proxy label, other problems only on Add proxy's tooltip; a reopen starts the paste box empty", async () => {
    relayGet.mockResolvedValue({ proxies: [{ label: "1.2.3.4:9090" }], pool: { size: 0, account_ids: [] }, accounts: [] });
    render(<ProxiesTable />, { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/proxies"));
    fireEvent.click(screen.getByRole("button", { name: "Add new proxy" }));
    const dialog = within(screen.getByRole("dialog", { name: "Add new proxy" }));
    const add = dialog.getByRole("button", { name: "Add proxy" });
    await waitFor(() => expect(add).toHaveAttribute("title", "Fill in Proxy label"));
    expect(dialog.queryByText("Fill in Proxy label")).toBeNull();

    fireEvent.click(dialog.getByRole("radio", { name: "http" }));
    fireEvent.change(dialog.getByLabelText("IP address"), { target: { value: "1.2.3.4" } });
    fireEvent.change(dialog.getByLabelText("Port"), { target: { value: "9090" } });
    expect(dialog.getByText('A proxy named "1.2.3.4:9090" already exists')).toBeInTheDocument();
    expect(add).toBeDisabled();

    fireEvent.change(dialog.getByLabelText("Paste proxies (one per line)"), { target: { value: "u:p@5.5.5.5:1" } });
    fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Add new proxy" }));
    expect(screen.getByLabelText("Paste proxies (one per line)")).toHaveValue("");
    expect(screen.getByLabelText("IP address")).toHaveValue("");
    expect(screen.getByLabelText("Port")).toHaveValue("");
    expect(screen.getByRole("radio", { name: "http" })).not.toBeChecked();
  });
});

describe("ProxiesTable proxy health", () => {
  it("reads Unavailable with the reason while the relay holds a proxy bad, whatever its stored IP", async () => {
    relayGet.mockResolvedValue({
      proxies: [{
        label: "hu-1", host: "p.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.7",
        health: { state: "bad", errors: 3, bad_since: 1_800_000_000, next_recheck_at: 1_800_000_040 },
      }, {
        label: "hu-2", host: "q.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.8",
        health: { state: "healthy", errors: 0 },
      }],
      pool: { size: 0, account_ids: [] },
      accounts: [],
    });
    render(<ProxiesTable />, { wrapper });
    await screen.findByText("hu-1");
    expect(screen.getByText(/unreachable since .* \(3 refused\) — recheck at/)).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.8")).toBeInTheDocument();
    expect(screen.queryByText("203.0.113.7")).not.toBeInTheDocument();
  });
});

describe("ProxiesTable refusal rate", () => {
  it("shows refusing N% over the window next to the health text, only when the provider refused a call", async () => {
    const refusals = (refused: number, calls: number, pct: number) => ({ window_s: 600, refused, calls, pct });
    relayGet.mockResolvedValue({
      proxies: [{
        label: "hu-1", host: "p.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.7",
        health: { state: "healthy", errors: 0, refusals: refusals(32, 100, 32.4), inflight: 2, inflight_peak: 6 },
      }, {
        label: "hu-2", host: "q.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.8",
        health: { state: "healthy", errors: 0, refusals: refusals(0, 40, 0) },
      }, {
        label: "hu-3", host: "r.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.9",
        health: { state: "bad", bad_reason: "down", errors: 3, bad_since: 1_800_000_000, refusals: refusals(9, 20, 45) },
      }, {
        label: "hu-4", host: "s.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.10",
        health: { state: "bad", bad_reason: "flapping", errors: 0, bad_since: 1_800_000_000,
                  next_recheck_at: 1_800_000_060, refusals: refusals(27, 100, 27.2) },
      }, {
        label: "hu-5", host: "t.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.11",
        health: { state: "bad", bad_reason: "flapping", errors: 0, bad_since: 1_800_000_000,
                  next_recheck_at: 1_800_000_060, refusals: { window_s: 600, refused: 0, calls: 3, pct: 0 } },
      }, {
        label: "hu-6", host: "u.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.12",
        health: { state: "healthy", errors: 0, refusals: { window_s: 45, refused: 9, calls: 30, pct: 30 } },
      }, {
        // An Agency's owner: the share alone (the counts are every Agency's traffic: the site owner's).
        label: "hu-7", host: "v.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.13",
        health: { state: "healthy", errors: 0, refusals: { window_s: 600, pct: 12.6 } },
      }, {
        label: "hu-8", host: "w.invalid", port: 8080, scheme: "http", assigned_accounts: [], verified_ip: "203.0.113.14",
        health: { state: "healthy", errors: 0, refusals: { window_s: 600, pct: 0 } },
      }],
      pool: { size: 0, account_ids: [] },
      accounts: [],
    });
    render(<ProxiesTable />, { wrapper });
    await screen.findByText("hu-1");
    expect(screen.getByText("203.0.113.7 · refusing 32% (10 min)")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.8")).toBeInTheDocument();
    expect(screen.getByText(/unreachable since .* \(3 refused\) — rechecking · refusing 45% \(10 min\)/)).toBeInTheDocument();
    // Bad from flapping: the rate is the reason, in plain words; no "unreachable", no "(0 refused)".
    expect(screen.getByText(/^refusing 27% \(10 min\) since .* — recheck at .*$/)).toBeInTheDocument();
    expect(screen.queryByText(/0 refused/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/unreachable/)).toHaveLength(1);
    // Flap-bad with nothing refused left in the window: no "refusing 0%".
    expect(screen.getByText(/^was refusing — recheck at .*$/)).toBeInTheDocument();
    expect(screen.queryByText(/refusing 0%/)).not.toBeInTheDocument();
    // A window under a minute reads in seconds, never "(0 min)".
    expect(screen.getByText("203.0.113.12 · refusing 30% (45 s)")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.13 · refusing 13% (10 min)")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.14")).toBeInTheDocument();
    expect(screen.getAllByText(/refusing \d/)).toHaveLength(5);
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

describe("ProxiesTable delete modal", () => {
  it("is a modal-stack dialog: Escape closes it, deletes nothing, and focus returns to the row's Delete", async () => {
    relayGet.mockResolvedValue({
      proxies: [{ label: "hu-1", host: "p.invalid", port: 8080, scheme: "http", assigned_accounts: [] }],
      pool: { size: 0, account_ids: [] },
      accounts: [],
    });
    const user = userEvent.setup();
    render(<ProxiesTable />, { wrapper });
    const trigger = await screen.findByRole("button", { name: "Delete" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Delete proxy" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.contains(document.activeElement)).toBe(true);
    // Tab stays inside the dialog.
    for (let i = 0; i < 4; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(trigger);
    expect(relayDelete).not.toHaveBeenCalled();
  });
});

/** antd's prev5 / next5 run (rc-pagination), on purpose not ui/ifPager's `pageItems` "…" run. */
describe("pagerItems", () => {
  it.each<[string, number, number, Array<number | "prev5" | "next5">]>([
    ["1 page", 1, 1, [1]],
    ["≤7 pages: every page", 4, 7, [1, 2, 3, 4, 5, 6, 7]],
    ["first of 20", 1, 20, [1, 2, 3, 4, 5, "next5", 20]],
    ["3 of 20: no prev5 yet", 3, 20, [1, 2, 3, 4, 5, "next5", 20]],
    ["5 of 20: prev5 appears", 5, 20, [1, "prev5", 3, 4, 5, 6, 7, "next5", 20]],
    ["middle of 20", 10, 20, [1, "prev5", 8, 9, 10, 11, 12, "next5", 20]],
    ["18 of 20: no next5", 18, 20, [1, "prev5", 16, 17, 18, 19, 20]],
    ["last of 20", 20, 20, [1, "prev5", 16, 17, 18, 19, 20]],
  ])("%s", (_, page, pages, items) => {
    expect(pagerItems(page, pages)).toEqual(items);
  });
});

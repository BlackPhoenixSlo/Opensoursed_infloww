/**
 * BillingTab — the self-hosted, free line, then the support block (tip link + crypto addresses); no request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import BillingTab, { WALLETS } from "@/components/settings/BillingTab";

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn(async () => new Response("{}", { status: 404 }));
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BillingTab", () => {
  it("is headed \"Billing\": free, then a tip link and one copyable address per wallet", () => {
    renderWithProviders(<BillingTab />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Billing$/);
    expect(screen.getByText(/is self-hosted and free: nothing to pay, no invoices\.$/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "jackbase.me/tip" })).toHaveAttribute("href", "https://jackbase.me/tip");
    for (const w of WALLETS) expect(screen.getByText(w.address)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(WALLETS.length);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

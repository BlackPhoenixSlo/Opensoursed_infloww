/**
 * BillingTab — one self-hosted, free line; no buttons, no table, no request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import BillingTab from "@/components/settings/BillingTab";

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
  it("is headed \"Billing\" and says only that it is self-hosted and free", () => {
    renderWithProviders(<BillingTab />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Billing$/);
    expect(screen.getByText(/is self-hosted and free: nothing to pay, no invoices\.$/)).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

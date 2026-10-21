/**
 * BillingTab — the static Billing Panel (docs/spec/settings-tabs/phase-05-billing-balance-about.md,
 * Testing Decisions). `globalThis.fetch` is a spy set before every render, so "makes no request" is an
 * assertion about the wire, checked after render, after each subtab switch and after every click.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import BillingTab from "@/components/settings/BillingTab";

const ACTIONS = ["Pricing plans", "Update card", "Cancel subscription", "Billing information", "Make a Payment"];

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn(async () => new Response("{}", { status: 404 }));
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const panel = () => within(screen.getByRole("tabpanel"));
/** The invoice table's column heads and body rows' text. */
function invoiceTable() {
  const table = panel().getByRole("table");
  return {
    columns: within(table).getAllByRole("columnheader").map((h) => h.textContent),
    rows: within(table).getAllByRole("row").slice(1).map((r) => r.textContent),
  };
}
const EMPTY_TABLE = { columns: ["Invoice", "Period", "Amount", "Status"], rows: ["No invoices"] };

describe("BillingTab", () => {
  it("is headed \"Billing\" and opens on \"Infloww subscription\" of two subtabs", () => {
    renderWithProviders(<BillingTab />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Billing$/);
    const tabs = within(screen.getByRole("tablist", { name: "Billing" })).getAllByRole("tab");
    expect(tabs.map((t) => [t.textContent, t.getAttribute("aria-selected")])).toEqual([
      ["Infloww subscription", "true"],
      ["AI Copilot", "false"],
    ]);
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Infloww subscription");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("\"Infloww subscription\" shows the free plan card, the five Not wired actions, then the empty invoice table", () => {
    renderWithProviders(<BillingTab />);
    expect(panel().getByText("Inflowwww — self-hosted, free")).toBeInTheDocument();
    const buttons = panel().getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(ACTIONS);
    for (const b of buttons) {
      expect(b).toBeDisabled();
      expect(b).toHaveAttribute("title", "not wired");
    }
    const makePayment = panel().getByRole("button", { name: "Make a Payment" });
    expect(makePayment.compareDocumentPosition(panel().getByRole("table")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(invoiceTable()).toEqual(EMPTY_TABLE);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("\"AI Copilot\" shows only the empty invoice table, and switching back restores the plan card", () => {
    renderWithProviders(<BillingTab />);
    fireEvent.click(screen.getByRole("tab", { name: "AI Copilot" }));
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: "AI Copilot" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("AI Copilot");
    expect(panel().queryByText("Inflowwww — self-hosted, free")).not.toBeInTheDocument();
    expect(panel().queryAllByRole("button")).toEqual([]);
    expect(invoiceTable()).toEqual(EMPTY_TABLE);

    fireEvent.click(screen.getByRole("tab", { name: "Infloww subscription" }));
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(panel().getByText("Inflowwww — self-hosted, free")).toBeInTheDocument();
  });

  it("draws the invoice cells at 13px", () => {
    renderWithProviders(<BillingTab />);
    expect(panel().getByRole("table")).toHaveClass("text-[length:var(--if-fs-table)]");
  });

  it("clicking every action makes no request", () => {
    renderWithProviders(<BillingTab />);
    for (const name of ACTIONS) {
      fireEvent.click(screen.getByRole("button", { name }));
      expect(fetchSpy).not.toHaveBeenCalled();
    }
  });
});

/**
 * MessageDashboardForm — Infloww's staged filter form (page-parity 30): nothing applies until Search, Search hands
 * up every wired param plus the tab's kind, Reset clears and applies, and the unwired choices say so.
 * Every identifier is invented (this repo mirrors to a public one).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [{ id: "100000001", nickname: "Creator A" }],
}));
vi.mock("@/hooks/useRoster", () => ({
  useRoster: () => ({ rows: [{ id: 5, display_name: "Employee Ann" }] }),
}));

import { renderWithProviders } from "@/test-utils";
import MessageDashboardForm, { initialParams } from "./MessageDashboardForm";

afterEach(cleanup);

async function pick(field: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: field }));
  await userEvent.click(within(screen.getByRole("listbox", { name: field })).getByRole("option", { name: option }));
}

describe("MessageDashboardForm", () => {
  it("applies nothing while typing; Search applies", async () => {
    const onSearch = vi.fn();
    renderWithProviders(<MessageDashboardForm kind="direct" onSearch={onSearch} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Search for Creator message" }), "hello");
    await userEvent.type(screen.getByRole("textbox", { name: "Sent to" }), "fanname");
    expect(onSearch).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch).toHaveBeenCalledTimes(1);
    expect(onSearch.mock.calls[0][0]).toMatchObject({ q: "hello", fan_query: "fanname", fan_id: null, kind: "direct" });
  });

  it("sends every wired filter and the tab's kind", async () => {
    const onSearch = vi.fn();
    renderWithProviders(<MessageDashboardForm kind="direct" onSearch={onSearch} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Search for Creator message" }), "promo");
    await pick("Sender", "Employee Ann");
    await pick("Creator", "Creator A");
    await userEvent.type(screen.getByRole("textbox", { name: "Minimum price" }), "10");
    await userEvent.type(screen.getByRole("textbox", { name: "Maximum price" }), "4.5");
    await pick("Purchased", "Paid");
    await pick("Status", "Unsent");
    await pick("Source", "Employee");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(onSearch).toHaveBeenCalledWith({
      q: "promo",
      employee_id: 5,
      account_id: "100000001",
      fan_id: null,
      fan_query: "",
      // A reversed pair is swapped, as Infloww does.
      min_price_cents: 450,
      max_price_cents: 1000,
      status: "paid",
      type: "paid",
      unsent_only: true,
      sender_type: "employee",
      kind: "direct",
    });
  });

  it("marks Purchased not wired on the mass tab, whose read ignores status, and sends the mass kind", async () => {
    const onSearch = vi.fn();
    renderWithProviders(<MessageDashboardForm kind="mass" onSearch={onSearch} />);
    const purchased = screen.getByRole("combobox", { name: "Purchased" });
    expect(purchased).toBeDisabled();
    expect(purchased.closest("[title]")).toHaveAttribute("title", "not wired");
    await pick("Status", "Unsent");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch.mock.calls[0][0]).toMatchObject({ status: "all", type: "all", unsent_only: true, kind: "mass" });
  });

  it("draws a field at its default All in the placeholder grey, a picked value in the text colour", async () => {
    renderWithProviders(<MessageDashboardForm kind="direct" onSearch={vi.fn()} />);
    const idle = (name: string) => screen.getByRole("combobox", { name }).parentElement!.className.includes("text-muted");
    expect(idle("Sender")).toBe(true);
    expect(idle("Source")).toBe(true);
    await pick("Sender", "Employee Ann");
    expect(idle("Sender")).toBe(false);
  });

  it("reads #<id> in Sent to as one fan, which a ?fan_id= link fills in", async () => {
    const onSearch = vi.fn();
    renderWithProviders(<MessageDashboardForm kind="direct" fanId={7} onSearch={onSearch} />);
    expect(screen.getByRole("textbox", { name: "Sent to" })).toHaveValue("#7");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch.mock.calls[0][0]).toMatchObject({ fan_id: "7", fan_query: "" });
    expect(initialParams("direct", 7)).toMatchObject({ fan_id: "7" });
  });

  it("maps Source AI chatbot to automation sends", async () => {
    const onSearch = vi.fn();
    renderWithProviders(<MessageDashboardForm kind="direct" onSearch={onSearch} />);
    await pick("Source", "AI chatbot");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch.mock.calls[0][0]).toMatchObject({ sender_type: "automation" });
  });

  it("Reset clears the form and applies the cleared form", async () => {
    const onSearch = vi.fn();
    renderWithProviders(<MessageDashboardForm kind="direct" fanId={7} onSearch={onSearch} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Search for Creator message" }), "hello");
    await pick("Purchased", "Unpaid");
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect(onSearch).toHaveBeenCalledWith(initialParams("direct"));
    expect(screen.getByRole("textbox", { name: "Search for Creator message" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Sent to" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Purchased" })).toHaveTextContent("All");
  });

  it("shows the unwired choices disabled, titled not wired", async () => {
    renderWithProviders(<MessageDashboardForm kind="direct" onSearch={vi.fn()} />);
    const type = screen.getByRole("combobox", { name: "Type" });
    expect(type).toBeDisabled();
    expect(type.closest("[title]")).toHaveAttribute("title", "not wired");

    await userEvent.click(screen.getByRole("combobox", { name: "Source" }));
    const copilot = screen.getByRole("option", { name: "AI Copilot" });
    expect(copilot).toHaveAttribute("aria-disabled", "true");
    expect(within(copilot).getByTitle("not wired")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("combobox", { name: "Status" }));
    expect(screen.getByRole("option", { name: "Sent" })).toHaveAttribute("aria-disabled", "true");
  });
});

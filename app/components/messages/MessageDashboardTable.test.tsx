import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";

vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ data: { accounts: [] } }),
}));
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: () => true }));

import { renderWithProviders } from "@/test-utils";
import type { PaidMessageRow } from "@/hooks/usePaidMessages";
import MessageDashboardTable, { COLUMNS, replyTime } from "./MessageDashboardTable";

const BASE: PaidMessageRow = {
  account_id: "100000001",
  fan_id: 200000002,
  message_id: 300000003,
  fan: { username: "testfan", display_name: "Test Fan", avatar_url: null },
  body: "Hello there",
  media_count: 0,
  price_cents: 0,
  is_paid: false,
  direction: "out",
  sent_at: "2026-10-19T15:04:00",
  purchased_at: null,
  sent_by_employee_id: 5,
  employee_name: "Employee Ann",
  automation_kind: null,
  reply_seconds: 130,
  is_unsent: false,
};

function renderRows(rows: PaidMessageRow[]) {
  return renderWithProviders(
    <MessageDashboardTable rows={rows} reportTz="UTC" loading={false} hasNextPage={false}
      isFetchingNextPage={false} fetchNextPage={vi.fn()} />,
  );
}

function cells(rowIndex: number): string[] {
  const row = screen.getAllByRole("row")[rowIndex + 1];
  return within(row).getAllByRole("cell").map((c) => c.textContent ?? "");
}

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    disconnect() {}
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MessageDashboardTable", () => {
  it("draws Infloww's eleven headers in order", () => {
    renderRows([]);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Sender", "Creator", "Message", "Sent time", "Reply time", "Price", "Purchased", "Source", "Status", "Sent to",
      "Actions",
    ]);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("fills a direct row: sender, two-line sent time in the report zone, reply time, Sent, the fan", () => {
    renderRows([BASE]);
    const c = cells(0);
    expect(c[0]).toBe("Employee Ann");
    expect(c[2]).toBe("Hello there");
    expect(c[3]).toBe("3:04 PMOct 19, 2026");
    expect(c[4]).toBe("2m 10s");
    expect(c[5]).toBe("--");
    expect(c[6]).toBe("--");
    expect(c[7]).toBe("Employee");
    expect(c[8]).toBe("Sent");
    expect(c[9]).toBe("Test Fan");
    expect(screen.getByRole("link", { name: "Open chat" })).toHaveAttribute("href", "/messages-pro/100000001/200000002");
    expect(screen.getByText("You have reached the end of the page")).toBeInTheDocument();
  });

  it("shows -- for no reply time, and a priced purchase as bought, pending sales included", () => {
    renderRows([{ ...BASE, reply_seconds: null, price_cents: 1500, is_paid: true, purchased_at: null }]);
    const c = cells(0);
    expect(c[4]).toBe("--");
    expect(c[5]).toBe("$15");
    expect(screen.getByRole("img", { name: "Paid" })).toBeInTheDocument();
    expect(replyTime(0)).toBe("--");
    expect(replyTime(3725)).toBe("62m 5s");
  });

  it("shows a mass summary as N fans and N of M bought, with no Unsend", () => {
    renderRows([{
      ...BASE, message_id: 5_000_000_000_000_001, is_mass_summary: true, mass_run_id: 9, recipient_count: 40,
      purchased_count: 3, price_cents: 999, reply_seconds: null, employee_name: null, sender_name: "mass-ann",
      automation_kind: "send_mass_message",
    }]);
    const c = cells(0);
    expect(c[0]).toBe("mass-ann");
    expect(c[6]).toBe("3 of 40");
    expect(c[7]).toBe("AI chatbot");
    expect(c[9]).toBe("40 fans");
    expect(screen.queryByRole("button", { name: /unsend/i })).toBeNull();
  });

  it("offers Unsend only where canOfferUnsend, and shows an unsent row as Unsent", () => {
    renderRows([
      { ...BASE, sent_at: new Date().toISOString() },
      { ...BASE, message_id: 300000004, is_unsent: true, unsent_reason: "manual:chat" },
    ]);
    expect(screen.getAllByRole("button", { name: "Unsend" })).toHaveLength(1);
    expect(cells(1)[8]).toBe("Unsent");
  });

  it("shows the error state with Retry", () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <MessageDashboardTable rows={[]} reportTz="UTC" loading={false} error onRetry={onRetry} hasNextPage={false}
        isFetchingNextPage={false} fetchNextPage={vi.fn()} />,
    );
    screen.getByRole("button", { name: "Retry" }).click();
    expect(onRetry).toHaveBeenCalled();
  });

  it("keeps loading pages after an error and Retry: the remounted sentinel is observed", () => {
    const observed: Element[] = [];
    let fire: IntersectionObserverCallback = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: IntersectionObserverCallback) { fire = cb; }
      observe(el: Element) { observed.push(el); }
      disconnect() {}
    });
    const fetchNextPage = vi.fn();
    const table = (error: boolean) => (
      <MessageDashboardTable rows={[BASE]} reportTz="UTC" loading={false} error={error} onRetry={vi.fn()}
        hasNextPage isFetchingNextPage={false} fetchNextPage={fetchNextPage} />
    );
    const { rerender } = renderWithProviders(table(false));
    rerender(table(true));
    rerender(table(false));
    const live = observed.at(-1)!;
    expect(live.isConnected).toBe(true);
    fire([{ isIntersecting: true, target: live } as unknown as IntersectionObserverEntry], {} as IntersectionObserver);
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });
});

describe("pinned Actions", () => {
  it("pins right from sm up only: on a phone the Message column gets the width (it sat off-screen)", () => {
    renderWithProviders(<MessageDashboardTable rows={[BASE]} reportTz="UTC" loading={false} hasNextPage={false}
      isFetchingNextPage={false} fetchNextPage={vi.fn()} />);
    expect(screen.getByRole("columnheader", { name: "Actions" }).className).toContain("max-sm:static");
    const cell = screen.getByRole("link", { name: "Open chat" }).closest("td")!;
    expect(cell.className).toMatch(/\bsticky\b.*max-sm:static/);
  });
});

describe("column widths", () => {
  it("Sent time ends inside the 856px a 1280px window shows beside the pinned Actions (it read \"Sent t\")", () => {
    const upTo = COLUMNS.slice(0, COLUMNS.findIndex((c) => c.title === "Sent time") + 1);
    expect(upTo.reduce((n, c) => n + c.width, 0)).toBeLessThanOrEqual(856);
  });
});

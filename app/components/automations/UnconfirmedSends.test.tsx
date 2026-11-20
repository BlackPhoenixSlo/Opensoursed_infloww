/**
 * Auto Funnel's "May not have sent" rows: beside Retry, "It went through" asks first (treated as sent, not sent
 * again), then POSTs …/dismiss with the hint the user saw; success drops the row, a failure shows its error and keeps
 * it. Declining makes no call. A row with a hint shows "Sent to this fan at …: …".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const relay = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({ ...(await orig<typeof import("@/lib/relay")>()), relay }));

import { RelayError } from "@/lib/relay";
import { UnconfirmedSends } from "@/components/automations/UnconfirmedSends";
import type { UnconfirmedRow } from "@/components/automations/unconfirmedSendsReducer";

const ROW: UnconfirmedRow = {
  kind: "funnel", fan_id: "42", mass_run_id: 7, step: 2, step_label: "STEP 2", since: "2026-11-20T10:00:00Z",
  last_error: "may not have sent: ReadTimeout", state: "UNCONFIRMED",
  hint: { message_id: "9001", at: "2026-11-20T10:00:05Z", text: "hey babe, check this out" },
};

let rows: UnconfirmedRow[];
beforeEach(() => {
  rows = [ROW];
  relay.get.mockReset().mockImplementation(async () => ({ rows }));
  relay.post.mockReset();
});
afterEach(cleanup);

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><UnconfirmedSends accountId="acc1" /></QueryClientProvider>);
  return within(await screen.findByTestId("unconfirmed-send-row"));
}

const click = async (el: HTMLElement) => { await act(async () => { fireEvent.click(el); }); };

describe("UnconfirmedSends · It went through", () => {
  it("shows both buttons and the hint line", async () => {
    const row = await mount();
    expect(row.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(row.getByRole("button", { name: "It went through" })).toBeTruthy();
    expect(row.getByTestId("unconfirmed-send-hint").textContent).toMatch(/^Sent to this fan at .+: hey babe, check this out$/);
  });

  it("confirms, POSTs dismiss with the hint, and drops the row", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    relay.post.mockImplementation(async () => { rows = []; return { status: "dismissed" }; });
    const row = await mount();
    await click(row.getByRole("button", { name: "It went through" }));
    expect(confirm.mock.calls[0][0]).toMatch(/treated as sent.*not sent again/);
    expect(relay.post).toHaveBeenCalledWith(
      "/admin/unconfirmed-sends/dismiss?account_id=acc1",
      { kind: "funnel", fan_id: "42", mass_run_id: 7, since: "2026-11-20T10:00:00Z", hint_message_id: "9001" },
      { accountId: "acc1" },
    );
    expect(screen.queryByTestId("unconfirmed-send-row")).toBeNull();
  });

  it("declining the confirm makes no call", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const row = await mount();
    await click(row.getByRole("button", { name: "It went through" }));
    expect(relay.post).not.toHaveBeenCalled();
    expect(screen.getByTestId("unconfirmed-send-row")).toBeTruthy();
  });

  it("a failure shows its error and keeps the row", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    relay.post.mockRejectedValue(new RelayError(409, {}, "still sending"));
    const row = await mount();
    await click(row.getByRole("button", { name: "It went through" }));
    expect(row.getByRole("alert").textContent).toBe("still sending");
    expect(screen.getByTestId("unconfirmed-send-row")).toBeTruthy();
    expect(row.getByRole("button", { name: "It went through" })).toHaveProperty("disabled", false);
  });
});

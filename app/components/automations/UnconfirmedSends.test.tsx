import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const relay = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({ ...(await orig<typeof import("@/lib/relay")>()), relay }));

import { RelayError } from "@/lib/relay";
import { UnconfirmedSends } from "@/components/automations/UnconfirmedSends";
import type { ListedRow, OpRow, UnconfirmedRow } from "@/components/automations/unconfirmedSendsReducer";

const ROW: UnconfirmedRow = {
  kind: "funnel", fan_id: "42", mass_run_id: 7, step: 2, step_label: "STEP 2", since: "2026-11-20T10:00:00Z",
  last_error: "may not have sent: ReadTimeout", state: "UNCONFIRMED",
  hint: { message_id: "9001", at: "2026-11-20T10:00:05Z", text: "hey babe, check this out" },
};

let rows: ListedRow[];
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

describe("UnconfirmedSends · Retry", () => {
  it("POSTs retry with the listed since", async () => {
    relay.post.mockImplementation(async () => { rows = []; return { status: "retried" }; });
    const row = await mount();
    await click(row.getByRole("button", { name: "Retry" }));
    expect(relay.post).toHaveBeenCalledWith(
      "/admin/unconfirmed-sends/retry?account_id=acc1",
      { kind: "funnel", fan_id: "42", mass_run_id: 7, since: "2026-11-20T10:00:00Z" },
      { accountId: "acc1" },
    );
    expect(screen.queryByTestId("unconfirmed-send-row")).toBeNull();
  });

  it("a 409 (the row changed since it was listed) keeps the row with the message and refetches it", async () => {
    relay.post.mockImplementation(async () => {
      rows = [{ ...ROW, since: "2026-11-20T10:20:00Z" }];
      throw new RelayError(409, {}, "this row changed since it was listed: refresh");
    });
    const row = await mount();
    const gets = relay.get.mock.calls.length;
    await click(row.getByRole("button", { name: "Retry" }));
    expect(row.getByRole("alert").textContent).toBe("this row changed since it was listed: refresh");
    expect(screen.getByTestId("unconfirmed-send-row")).toBeTruthy();
    expect(row.getByRole("button", { name: "Retry" })).toHaveProperty("disabled", false);
    expect(relay.get.mock.calls.length).toBeGreaterThan(gets);
  });
});

const OP: OpRow = {
  kind: "composer", op_id: "op-1", fan_id: "42", since: "2026-11-26T10:00:00Z", state: "UNCONFIRMED",
  retry_allowed: false, link: "chat",
};

describe("UnconfirmedSends · Cell mode (retry_allowed:false)", () => {
  it("hides Retry on a marked row, keeps It went through", async () => {
    rows = [{ ...ROW, retry_allowed: false }];
    const row = await mount();
    expect(row.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(row.getByRole("button", { name: "It went through" })).toBeTruthy();
    expect(screen.getByTestId("unconfirmed-sends").textContent).toMatch(/To resend, write a new message/);
  });

  it("an op row shows its chat link and Was sent / Not sent, never Retry", async () => {
    rows = [OP];
    const row = await mount();
    expect(row.getByTestId("unconfirmed-send-link").getAttribute("href")).toBe("/messages-pro/acc1/42");
    expect(row.getByRole("link").textContent).toBe("Open chat");
    expect(row.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(row.queryByRole("button", { name: "It went through" })).toBeNull();
    expect(row.getByRole("button", { name: "Was sent" })).toBeTruthy();
    expect(row.getByRole("button", { name: "Not sent" })).toBeTruthy();
  });

  it("a queue op links to the queue", async () => {
    rows = [{ ...OP, kind: "mass_job", fan_id: "mass:7", link: "queue" }];
    const row = await mount();
    expect(row.getByTestId("unconfirmed-send-link").getAttribute("href")).toBe("/growth/smart-messages");
    expect(row.getByRole("link").textContent).toBe("Open queue");
    expect(row.getByText("Mass job")).toBeTruthy();
  });

  it.each([["Not sent", "not_sent"], ["Was sent", "was_sent"]] as const)(
    "%s confirms, POSTs resolve and drops the row", async (label, outcome) => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      rows = [OP];
      relay.post.mockImplementation(async () => { rows = []; return { status: outcome }; });
      const row = await mount();
      await click(row.getByRole("button", { name: label }));
      expect(confirm.mock.calls.at(-1)?.[0]).toMatch(/Automations to this fan start again/);
      expect(relay.post).toHaveBeenCalledWith(
        "/admin/unconfirmed-sends/resolve?account_id=acc1", { op_id: "op-1", outcome }, { accountId: "acc1" },
      );
      expect(screen.queryByTestId("unconfirmed-send-row")).toBeNull();
    },
  );

  it("env unset rows (no retry_allowed) keep Retry and today's text", async () => {
    const row = await mount();
    expect(row.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(row.queryByTestId("unconfirmed-send-link")).toBeNull();
    expect(screen.getByTestId("unconfirmed-sends").textContent).toMatch(/then Retry if the fan didn.t get it/);
  });
});

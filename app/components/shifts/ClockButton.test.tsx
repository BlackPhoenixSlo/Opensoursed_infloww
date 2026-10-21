/**
 * The top bar's Clock button (w4-a, Infloww's `ClockInOrOut`): shown only while
 * ClockStatus lets the caller clock in or it has an open event, "Clock in" or
 * "Clock out" with the elapsed time, a confirm before each write, Infloww's
 * toast lines (read here from `lib/notices`, which the toast stack shows), a
 * chatter in two Agencies sent to `ClockDialog`, the heartbeat sent only after
 * real input, and the inactivity notice once per Auto clock out.
 *
 * Rendered with `fetch` mocked by URL; the ClockStatus double is mutable, so a
 * poll is a `refetchQueries`. Ids and names are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

let session: { user: { user_id: string; username: string } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: session.user, loading: false }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: session.chatter }) }));

import ClockButton, { ClockHeartbeat, useClockHeartbeat } from "@/components/shifts/ClockButton";
import { onNotice } from "@/lib/notices";
import { CLOCK_STATUS_KEY } from "@/lib/shifts";

const open = (id: number, in_utc = "2026-10-14T16:00:00Z") => ({
  clock_event_id: id, employee_id: 41, account_id: null, shift_id: null, in_utc, out_utc: null, close_reason: null,
});
type Status = {
  can_clock: boolean; reason: string | null; open: ReturnType<typeof open> | null;
  last_closed: { clock_event_id: number; out_utc: string; close_reason: string } | null;
  auto_clock_out_minutes: number; server_now: string;
};
const idle = (): Status => ({
  can_clock: true, reason: null, open: null, last_closed: null, auto_clock_out_minutes: 10,
  server_now: "2026-10-14T17:05:00Z",
});

let status: Status;
/** What `POST /clock-in` answers, or null for the event. */
let clockInRefusal: { status: number; detail: unknown } | null;
let fetchMock: ReturnType<typeof vi.fn>;
let notices: string[];
let unsubscribe: () => void;

const posts = () => fetchMock.mock.calls
  .filter(([, init]) => init?.method === "POST")
  .map(([url, init]) => ({ path: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined }));

beforeEach(() => {
  session = { user: null, chatter: { username: "chatter_one" } };
  status = idle();
  clockInRefusal = null;
  notices = [];
  unsubscribe = onNotice((n) => notices.push(n.text));
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method === "GET" && url === "/admin/shifts/clock-status") return jsonRes(status);
    if (method === "POST" && url === "/admin/shifts/clock-heartbeat") return jsonRes(status);
    if (method === "POST" && url === "/admin/shifts/clock-in") {
      if (clockInRefusal) return jsonRes({ detail: clockInRefusal.detail }, clockInRefusal.status);
      status = { ...status, open: open(7) };
      return jsonRes(status.open);
    }
    if (method === "POST" && url === "/admin/shifts/clock-out") {
      const closed = { ...status.open, out_utc: "2026-10-14T17:05:00Z", close_reason: "manual" };
      status = { ...status, open: null };
      return jsonRes(closed);
    }
    if (method === "GET" && url === "/admin/shifts/me") {
      return jsonRes({
        accounts: [{ account_id: "1000001", display_name: "creator_one", time_tracking_enabled: true,
          clock_in_reminder: false }],
        occurrences: [], open_clocks: [], reminder: null,
      });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  unsubscribe();
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const topButton = () => screen.findByRole("button", { name: /^Clock (in|out)/ });

describe("ClockButton", () => {
  it.each([
    ["the role is not enabled", { can_clock: false, reason: "role_not_enabled" }],
    ["time tracking is off", { can_clock: false, reason: "time_tracking_off" }],
  ])("renders nothing while %s and no event is open", async (_name, gate) => {
    status = { ...idle(), ...gate };
    const { container } = renderWithProviders(<ClockButton />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/admin/shifts/clock-status", expect.anything()));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(container).toBeEmptyDOMElement();
  });

  it("reads nothing and renders nothing with no session", async () => {
    session = { user: null, chatter: null };
    const { container } = renderWithProviders(<ClockButton />);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("an owner session reads the status too and shows Clock in when its role is ticked", async () => {
    session = { user: { user_id: "owner-1", username: "owner" }, chatter: null };
    renderWithProviders(<ClockButton />);
    expect(await topButton()).toHaveTextContent("Clock in");
  });

  it("asks \"Confirm clock in?\"; Cancel sends nothing; Yes clocks in agency-wide and says so", async () => {
    renderWithProviders(<ClockButton />);
    fireEvent.click(await topButton());
    const dialog = await screen.findByRole("dialog", { name: "Confirm clock in?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posts()).toEqual([]);

    fireEvent.click(await topButton());
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(notices).toEqual(["Clock in successful"]));
    expect(posts()).toEqual([{ path: "/admin/shifts/clock-in", body: {} }]);
    // The re-read status has the open event: the button turns into Clock out.
    expect(await screen.findByRole("button", { name: /^Clock out/ })).toBeInTheDocument();
  });

  it("clocked in, shows Clock out with the elapsed time, and Confirm clock out? closes that event", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-14T17:05:00Z"));
    status = { ...idle(), open: open(7) };
    renderWithProviders(<ClockButton />);
    const button = await screen.findByRole("button", { name: /^Clock out/ });
    expect(within(button).getByText("1 h 5 min")).toBeInTheDocument();
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Confirm clock out?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(notices).toEqual(["Clock out successful"]));
    expect(posts()).toEqual([{ path: "/admin/shifts/clock-out", body: { clock_event_id: 7 } }]);
  });

  it("in, out, in again says Clock in successful twice, as two toasts the toaster won't fold into one", async () => {
    const ids: string[] = [];
    const stop = onNotice((n) => ids.push(n.id));
    renderWithProviders(<ClockButton />);
    for (const [label, said] of [["Clock in", 1], ["Clock out", 2], ["Clock in", 3]] as const) {
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${label}`) }));
      fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Yes" }));
      await waitFor(() => expect(notices).toHaveLength(said));
    }
    stop();
    expect(notices).toEqual(["Clock in successful", "Clock out successful", "Clock in successful"]);
    expect(new Set(ids).size).toBe(3);
  });

  it("an open event shows Clock out even when the role was unticked since", async () => {
    status = { ...idle(), can_clock: false, reason: "role_not_enabled", open: open(8) };
    renderWithProviders(<ClockButton />);
    expect(await screen.findByRole("button", { name: /^Clock out/ })).toBeInTheDocument();
  });

  it("a 409 on clock-in says Infloww's \"You are already clocked in\"; a typed refusal keeps the Relay's message", async () => {
    clockInRefusal = { status: 409, detail: "already clocked in (event 3)" };
    renderWithProviders(<ClockButton />);
    fireEvent.click(await topButton());
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(notices).toEqual(["You are already clocked in"]));

    clockInRefusal = { status: 409, detail: { error: "time_tracking_off", message: "time tracking is off" } };
    fireEvent.click(await topButton());
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(notices).toEqual(["You are already clocked in", "time tracking is off"]));
  });

  it("a chatter in two Agencies opens the clock dialog to name a Creator, with no confirm", async () => {
    status = { ...idle(), reason: "pick_creator" };
    renderWithProviders(<ClockButton />);
    fireEvent.click(await topButton());
    expect(await screen.findByRole("dialog", { name: "Clock in and out" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Confirm clock in?" })).toBeNull();
    expect(posts()).toEqual([]);
  });

  it("says \"You have been clocked out due to inactivity\" once when an event it saw open comes back auto-closed", async () => {
    status = { ...idle(), open: open(21) };
    const { queryClient } = renderWithProviders(<ClockButton />);
    await screen.findByRole("button", { name: /^Clock out/ });
    status = { ...idle(), last_closed: { clock_event_id: 21, out_utc: "2026-10-14T17:00:00Z", close_reason: "auto" } };
    await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
    await waitFor(() => expect(notices).toEqual(["You have been clocked out due to inactivity"]));
    await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
    expect(notices).toEqual(["You have been clocked out due to inactivity"]);
    expect(await screen.findByRole("button", { name: /^Clock in/ })).toBeInTheDocument();
  });

  describe("the lost connection (fake timers)", () => {
    /** Closed by Auto clock out at `out_utc`; the server's clock reads 17:05 when the test starts. */
    const closedAuto = (id: number, out_utc = "2026-10-14T17:00:00Z"): Status => ({
      ...idle(), last_closed: { clock_event_id: id, out_utc, close_reason: "auto" },
    });

    it("a heartbeat that fails at the network level, then the event auto-closed, says the connection was lost, once", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      status = { ...idle(), open: open(7) };
      const { queryClient } = renderWithProviders(<ClockButton />);
      await screen.findByRole("button", { name: /^Clock out/ });
      // The network is down: the beat and the minute's status poll both fail.
      const answer = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async () => { throw new TypeError("Failed to fetch"); });
      fireEvent.pointerMove(window);
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(fetchMock.mock.calls.some(([u]) => u === "/admin/shifts/clock-heartbeat")).toBe(true);

      // It is back; the first read finds the event auto-closed after the failure.
      fetchMock.mockImplementation(answer);
      status = closedAuto(7, "2026-10-14T17:15:00Z");
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      await waitFor(() => expect(notices).toEqual(["You have been clocked out as your internet connection was lost."]));
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      expect(notices).toEqual(["You have been clocked out as your internet connection was lost."]);
    });

    it("a beat that fails after the server already closed the event (a laptop waking offline) says inactivity", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      status = { ...idle(), open: open(7) };
      const { queryClient } = renderWithProviders(<ClockButton />);
      await screen.findByRole("button", { name: /^Clock out/ });
      const answer = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async () => { throw new TypeError("Failed to fetch"); });
      fireEvent.pointerMove(window);
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });

      // The close (17:00) is before the failure (17:05 by the server's clock).
      fetchMock.mockImplementation(answer);
      status = closedAuto(7, "2026-10-14T17:00:00Z");
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      await waitFor(() => expect(notices).toEqual(["You have been clocked out due to inactivity"]));
    });

    it("beats that keep failing past the close (an outage longer than the deadline) say the connection was lost", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
      vi.setSystemTime(new Date("2026-10-14T17:05:00Z"));
      status = { ...idle(), open: open(7) };
      const { queryClient } = renderWithProviders(<ClockButton />);
      await screen.findByRole("button", { name: /^Clock out/ });
      const answer = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async () => { throw new TypeError("Failed to fetch"); });
      // Twenty minutes of input with the network down: the first beat fails at 17:06, the last at 17:25.
      for (let minute = 0; minute < 20; minute++) {
        fireEvent.pointerMove(window);
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      }

      // The server closed it at 17:15, after the first failure and before the last.
      fetchMock.mockImplementation(answer);
      status = { ...closedAuto(7, "2026-10-14T17:15:00Z"), server_now: "2026-10-14T17:25:00Z" };
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      await waitFor(() => expect(notices).toEqual(["You have been clocked out as your internet connection was lost."]));
    });

    it("with no network failure, an HTTP error on the heartbeat still ends in the inactivity text", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      status = { ...idle(), open: open(7) };
      const { queryClient } = renderWithProviders(<ClockButton />);
      await screen.findByRole("button", { name: /^Clock out/ });
      const answer = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
        if (url === "/admin/shifts/clock-heartbeat") return jsonRes({ detail: "boom" }, 500);
        return answer(url, init);
      });
      fireEvent.keyDown(window, { key: "a" });
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });

      status = closedAuto(7);
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      await waitFor(() => expect(notices).toEqual(["You have been clocked out due to inactivity"]));
    });

    it("a network failure followed by a successful status read no longer counts: a later Auto clock out is inactivity", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      status = { ...idle(), open: open(7) };
      const { queryClient } = renderWithProviders(<ClockButton />);
      await screen.findByRole("button", { name: /^Clock out/ });
      const answer = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async () => { throw new TypeError("Failed to fetch"); });
      fireEvent.pointerMove(window);
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      // The connection is back: this read answers with the event still open.
      fetchMock.mockImplementation(answer);
      status = { ...status, server_now: "2026-10-14T17:06:00Z" };
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      // Let the read render before the next one (React Query notifies on a later tick).
      await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

      status = closedAuto(7);
      await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
      await waitFor(() => expect(notices).toEqual(["You have been clocked out due to inactivity"]));
    });
  });

  it("does not announce an Auto clock out it never saw open, or a manual close", async () => {
    status = { ...idle(), last_closed: { clock_event_id: 22, out_utc: "2026-10-14T17:00:00Z", close_reason: "auto" } };
    const { queryClient } = renderWithProviders(<ClockButton />);
    await topButton();
    status = { ...idle(), open: open(23) };
    await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
    status = { ...idle(), last_closed: { clock_event_id: 23, out_utc: "2026-10-14T17:00:00Z", close_reason: "manual" } };
    await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(notices).toEqual([]);
  });
});

describe("useClockHeartbeat", () => {
  function Beat({ minutes, id = 31 }: { minutes: number; id?: number | null }) {
    useClockHeartbeat(id === null ? null : open(id), minutes, () => {});
    return null;
  }
  const beats = () => posts().filter((p) => p.path === "/admin/shifts/clock-heartbeat").length;

  it("beats every 60 seconds, only after input since the last beat, and the answer replaces the status", async () => {
    vi.useFakeTimers();
    status = { ...idle(), open: open(31) };
    const { queryClient } = renderWithProviders(<Beat minutes={10} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(beats()).toBe(0);

    fireEvent.pointerMove(window);
    await act(async () => { await vi.advanceTimersByTimeAsync(59_000); });
    expect(beats()).toBe(0);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(beats()).toBe(1);
    expect(queryClient.getQueryData(CLOCK_STATUS_KEY)).toEqual(status);

    // No input since that beat: the next interval sends nothing.
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(beats()).toBe(1);
    fireEvent.keyDown(window, { key: "a" });
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(beats()).toBe(2);
  });

  it("ClockHeartbeat, the button-less one Messages Pro mounts, beats after input and announces an Auto clock out", async () => {
    vi.useFakeTimers();
    status = { ...idle(), open: open(31) };
    const { container, queryClient } = renderWithProviders(<ClockHeartbeat />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(container).toBeEmptyDOMElement();
    fireEvent.keyDown(window, { key: "a" });
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(beats()).toBe(1);

    status = { ...idle(), last_closed: { clock_event_id: 31, out_utc: "2026-10-14T17:00:00Z", close_reason: "auto" } };
    await act(async () => { await queryClient.refetchQueries({ queryKey: CLOCK_STATUS_KEY }); });
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    expect(notices).toEqual(["You have been clocked out due to inactivity"]);
  });

  it("sends nothing with no open event", async () => {
    vi.useFakeTimers();
    renderWithProviders(<Beat minutes={10} id={null} />);
    fireEvent.pointerMove(window);
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(beats()).toBe(0);
  });

  it("beats every 30 seconds when Auto clock out is 3 minutes or less", async () => {
    vi.useFakeTimers();
    renderWithProviders(<Beat minutes={3} />);
    fireEvent.pointerDown(window);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(beats()).toBe(1);
  });
});

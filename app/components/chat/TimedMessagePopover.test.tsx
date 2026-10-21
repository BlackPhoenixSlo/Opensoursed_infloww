/**
 * Timed message (seam 1: the `Composer`; docs/spec/phase-04-composer-ppv-vault.md,
 * Timed message and Contracts). ⏱ "Timed message" holds the draft for a whole
 * number of minutes, 1 to 60, through the Composer's existing delayed submit:
 * every check asserts at `onSend` or on "Start"'s enabled state.
 *
 * Ticket 31 adds the Timed message and removes the ▾ quick-send split.
 * Ticket 32 adds the "Timed reminder" tab: a per-Fan countdown that never
 * sends, held at module level and under
 * `chatterly:timed-reminder:<accountId>:<fanId>`. Module state outlives a
 * test, so each reminder test uses its own Fan.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { renderComposer, resetComposerHarness, routeRelay, tooltipOf } from "./composerTestHarness";

beforeEach(() => resetComposerHarness());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const NOW = "2026-10-13T10:00:00.000Z";
const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;

/** Freeze the clock. Only Date is faked: user-event's timers stay real. */
function freezeClock() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(NOW));
}

/** Open ⏱ and return its minutes field and "Start". */
async function openTimed(user: UserEvent) {
  await user.click(
    within(screen.getByRole("toolbar", { name: "Composer buttons" }))
      .getByRole("button", { name: "Timed message" }),
  );
  const pop = within(screen.getByRole("region", { name: "Timed message" }));
  return {
    minutes: pop.getByRole("textbox", { name: "Minutes" }) as HTMLInputElement,
    start: pop.getByRole("button", { name: "Start" }),
  };
}

/** Pick the synthetic GIFs, in order, through the GIF picker. */
async function pickGifs(user: UserEvent, titles: string[]) {
  routeRelay("/giphy/proxy/gifs/trending", () => ({
    data: titles.map((title, i) => ({
      type: "gif", id: `gif-synthetic-${i + 1}`, title,
      images: { original: { url: `https://gif.test/${i + 1}.gif` } },
    })),
    pagination: { total_count: titles.length, offset: 0 },
  }));
  for (const title of titles) {
    await user.click(screen.getByRole("button", { name: "GIF" }));
    await user.click(await screen.findByRole("button", { name: title }));
  }
}

describe("Timed message: the minutes field", () => {
  it('"Start" takes whole minutes 1 to 60 and 60 sends once at now plus 60 minutes', async () => {
    freezeClock();
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi");
    const { minutes, start } = await openTimed(user);
    expect(minutes.value).toBe("5");
    expect(start).toBeEnabled();

    for (const bad of ["0", "61", "2.5", ""]) {
      await user.clear(minutes);
      if (bad) await user.type(minutes, bad);
      expect(start).toBeDisabled();
      expect(tooltipOf(start)).toMatch(/1 to 60/);
    }
    for (const good of ["1", "60"]) {
      await user.clear(minutes);
      await user.type(minutes, good);
      expect(start).toBeEnabled();
    }
    await user.click(start);

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi", scheduledAt: "2026-10-13T11:00:00.000Z" });
  });

  it('"Start" is disabled for an empty draft and in a blocked chat', async () => {
    const user = userEvent.setup();
    const { unmount } = await renderComposer();

    let { start } = await openTimed(user);
    expect(start).toBeDisabled();
    expect(tooltipOf(start)).toMatch(/Type a message/);
    unmount();

    await renderComposer({ canSend: false, cannotSendReason: "Fan unsubscribed" });
    await user.type(textbox(), "hi");
    ({ start } = await openTimed(user));
    expect(start).toBeDisabled();
    expect(tooltipOf(start)).toMatch(/disabled for this chat/);
  });
});

describe("Timed message: GIFs", () => {
  it('"Start" is disabled with two GIFs', async () => {
    const user = userEvent.setup();
    await renderComposer();

    await pickGifs(user, ["Synthetic wave", "Synthetic wink"]);
    const { start } = await openTimed(user);

    expect(start).toBeDisabled();
    expect(tooltipOf(start)).toMatch(/GIF/);
  });

  it('"Start" is disabled with one GIF at 16, and one GIF at 15 sends once with giphyId', async () => {
    freezeClock();
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await pickGifs(user, ["Synthetic wave"]);
    const { minutes, start } = await openTimed(user);
    await user.clear(minutes);
    await user.type(minutes, "16");
    expect(start).toBeDisabled();
    expect(tooltipOf(start)).toMatch(/GIF/);

    await user.clear(minutes);
    await user.type(minutes, "15");
    expect(start).toBeEnabled();
    await user.click(start);

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({
      text: "", giphyId: "gif-synthetic-1", scheduledAt: "2026-10-13T10:15:00.000Z",
    });
  });
});

describe('Timed message: precedence over "at"', () => {
  it('with "at" set to tomorrow, "Start" at 5 sends at now plus 5 minutes', async () => {
    freezeClock();
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi");
    await user.click(screen.getByRole("button", { description: "Schedule send for later" }));
    fireEvent.change(screen.getByLabelText("Send at"), { target: { value: "2026-10-14T12:00" } });
    expect(screen.getByRole("button", {
      name: "Schedule", description: "Enter to send · Shift+Enter for newline",
    })).toBeInTheDocument();

    const { start } = await openTimed(user);
    await user.click(start);

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi", scheduledAt: "2026-10-13T10:05:00.000Z" });
  });
});

/* ── Timed reminder ──────────────────────────────────────────────────── */

const ALERT = "Timed reminder — time's up";
const storageKey = (fanId: number) => `chatterly:timed-reminder:acct-1:${fanId}`;
const countdown = () => screen.queryByText(/^Timed reminder · \d+:\d\d$/);

/** Fake every timer from NOW, still advancing with the wall clock so React
 *  and user-event keep running; a test step adds a few real milliseconds. */
function fakeTimers() {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(NOW));
}

async function advance(ms: number) {
  await act(async () => { vi.advanceTimersByTime(ms); });
}

/** Open ⏱, switch to "Timed reminder", set the minutes and press "Start". */
async function startReminder(user: UserEvent, minutes: string) {
  await openTimed(user);
  await user.click(screen.getByRole("tab", { name: "Timed reminder" }));
  const pop = within(screen.getByRole("region", { name: "Timed message" }));
  const field = pop.getByRole("textbox", { name: "Minutes" });
  await user.clear(field);
  await user.type(field, minutes);
  await user.click(pop.getByRole("button", { name: "Start" }));
}

describe('Timed message: "Send at" presets (TODO.md A2)', () => {
  it("+5m … +60m show under the Timed message tab only", async () => {
    const user = userEvent.setup();
    await renderComposer({ fanId: 9301 });

    await openTimed(user);
    const presets = within(screen.getByRole("group", { name: "Send at presets" }));
    expect(presets.getAllByRole("button").map((b) => b.textContent)).toEqual(["+5m", "+10m", "+15m", "+30m", "+60m"]);
    await user.click(screen.getByRole("tab", { name: "Timed reminder" }));
    expect(screen.queryByRole("group", { name: "Send at presets" })).not.toBeInTheDocument();
  });
});

describe("Timed reminder", () => {
  it("1 minute counts down, alerts at zero, and never sends or asks for permission", async () => {
    fakeTimers();
    const shown: string[] = [];
    const requestPermission = vi.fn();
    vi.stubGlobal("Notification", Object.assign(
      function Notification(title: string) { shown.push(title); },
      { permission: "granted", requestPermission },
    ));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onSend } = await renderComposer({ fanId: 3201 });

    await user.type(textbox(), "hi");
    await startReminder(user, "1");

    expect(screen.getByText("Timed reminder · 1:00")).toBeInTheDocument();
    // The fire time is "Start" plus one minute, and "Start" came a few real
    // milliseconds after NOW.
    const firesIn = Number(localStorage.getItem(storageKey(3201))) - Date.parse(NOW);
    expect(firesIn).toBeGreaterThanOrEqual(60_000);
    expect(firesIn).toBeLessThan(61_000);
    await advance(30_000);
    expect(screen.getByText(/^Timed reminder · 0:[23]\d$/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await advance(30_000);
    expect(screen.getByRole("alert")).toHaveTextContent(ALERT);
    expect(countdown()).toBeNull();
    expect(shown).toEqual(["Timed reminder"]);
    expect(requestPermission).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();

    await user.click(within(screen.getByRole("alert")).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(localStorage.getItem(storageKey(3201))).toBeNull();
  });

  it("with the OS-notification setting off, zero alerts in the app only", async () => {
    fakeTimers();
    localStorage.setItem("chatterly:notif-settings:v1", JSON.stringify({ osPing: false }));
    const shown: string[] = [];
    vi.stubGlobal("Notification", Object.assign(
      function Notification(title: string) { shown.push(title); },
      { permission: "granted", requestPermission: vi.fn() },
    ));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await renderComposer({ fanId: 3202 });

    await startReminder(user, "1");
    await advance(60_000);
    expect(screen.getByRole("alert")).toHaveTextContent(ALERT);
    expect(shown).toEqual([]);
  });

  it("✕ before zero cancels it: no alert", async () => {
    fakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onSend } = await renderComposer({ fanId: 3202 });

    await startReminder(user, "1");
    await user.click(screen.getByRole("button", { name: "Cancel timed reminder" }));
    expect(countdown()).toBeNull();
    expect(localStorage.getItem(storageKey(3202))).toBeNull();

    await advance(120_000);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("survives unmounting and remounting the same account and Fan before zero", async () => {
    fakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { unmount } = await renderComposer({ fanId: 3203 });

    await startReminder(user, "2");
    unmount();
    await renderComposer({ fanId: 3204 });
    expect(countdown()).toBeNull();
    cleanup();

    await advance(30_000);
    await renderComposer({ fanId: 3203 });
    expect(screen.getByText("Timed reminder · 1:30")).toBeInTheDocument();
  });

  it("reload: a past fire time alerts on mount; a future one counts down in a fresh module", async () => {
    fakeTimers();
    localStorage.setItem(storageKey(3205), String(Date.parse(NOW) - 5_000));
    const { onSend } = await renderComposer({ fanId: 3205 });
    expect(await screen.findByRole("alert")).toHaveTextContent(ALERT);
    expect(onSend).not.toHaveBeenCalled();
    cleanup();

    vi.resetModules();
    localStorage.setItem(storageKey(3206), String(Date.parse(NOW) + 90_000));
    await renderComposer({ fanId: 3206 });
    expect(await screen.findByText("Timed reminder · 1:30")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

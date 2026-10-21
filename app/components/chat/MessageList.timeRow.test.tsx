/**
 * MessageList — the time row and Phase 4 Part C (look-and-feel ticket 146):
 * bubble shape, run stacking and one time row under each run's last bubble.
 *
 * The time row describe moved here out of `MessageList.test.tsx` (to keep
 * that file under 1000 lines), its placement test rewritten for Part C; the
 * same seam, the `MessageList` render test through `renderWithProviders`
 * with the relay mocked by URL, as that file does. Fixture identifiers are
 * invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));

import { renderWithProviders } from "@/test-utils";
import { MP } from "@/lib/messagesPro";
import { MessageList } from "@/components/chat/MessageList";
import { baseProps, bubbleBox, msg, timeRow } from "./messageListTestHarness";

const line = (c: HTMLElement, id: number) => bubbleBox(c, id).parentElement!.parentElement!;

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
});

/**
 * Phase 3 ticket 97 (spec gap rows L3, L5, L8), moved by Phase 4 Part C
 * (ticket 146, T12): the time row sits under a run's last bubble, "Sent by
 * <name>" sits in it on our bubbles, and an empty conversation reads "No
 * messages yet" with no trailing period.
 */
describe("MessageList time row and empty conversation", () => {
  it("puts 'Sent by <name>' and the receipt in the data-time-row under the run's last bubble, outside its box; the earlier bubble has none", () => {
    const createdAt = "2026-06-04T12:34:00.000Z";
    const sam = { employee_id: 7, display_name: "Sam", automation_kind: null, sender_name: null, color: null };
    const { container, getAllByText, getByRole } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} attribution={{ "39": sam, "40": sam }}
                   messages={[39, 40].map((id) => msg({ id, text: "ours", fromUser: { id: 555 }, createdAt }))} />,
    );
    const row = timeRow(container, 40)!;
    expect(row.hasAttribute("data-time-row")).toBe(true);
    expect(container.querySelectorAll("[data-time-row]")).toHaveLength(1);
    expect(timeRow(container, 39)).toBeNull();
    const sentBy = getAllByText("Sent by Sam");
    expect(sentBy).toHaveLength(1);
    expect(sentBy[0].getAttribute("title")).toBe("Sent by Sam");
    expect(row.contains(sentBy[0])).toBe(true);
    expect(row.contains(getByRole("img", { name: "Delivered" }))).toBe(true);
    expect(row.querySelector("time")?.getAttribute("datetime")).toBe(createdAt);
    expect(bubbleBox(container, 40).contains(row)).toBe(false);
  });

  it("an empty conversation shows 'No messages yet'", () => {
    const { getByText } = renderWithProviders(
      <MessageList {...baseProps} messages={[]} ownerUserId={555} />,
    );
    expect(getByText("No messages yet", { exact: true })).toBeTruthy();
  });
});

/**
 * Phase 4 Part C (spec T10-T12, stories 33-35): from md up a 6px bubble with a
 * square tail, a run's bubbles 2px apart, and the time row once under the run.
 */
describe("MessageList Part C: bubble shape, run stacking and the time row", () => {
  it("two same-minute outgoing messages, the first read and the second not, are two runs, each with its own time row and receipt", () => {
    const createdAt = "2026-06-04T12:34:00.000Z";
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} lastReadByPeerId={60}
                   messages={[60, 61].map((id) => msg({ id, text: `ours ${id}`, fromUser: { id: 555 }, createdAt }))} />,
    );
    const [read, unread] = [timeRow(container, 60), timeRow(container, 61)];
    expect(within(read!).getByRole("img", { name: "Seen" }).textContent).toBe("✓✓");
    expect(within(unread!).getByRole("img", { name: "Delivered" }).textContent).toBe("✓");
    expect(within(read!).queryByRole("img", { name: "Delivered" })).toBeNull();
    expect(container.querySelectorAll('[data-msg-avatar="creator"]')).toHaveLength(2);
  });

  it("bubbles take the T10 shape, a run's later line stacks under the one before, and the time row is dim text on its side", () => {
    const at = (mi: number, s: number) => new Date(2026, 5, 4, 9, mi, s).toISOString();
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[
        msg({ id: 101, text: "fan 101", fromUser: { id: 42 }, createdAt: at(41, 0) }),
        msg({ id: 102, text: "fan 102", fromUser: { id: 42 }, createdAt: at(41, 5) }),
        msg({ id: 103, text: "ours 103", fromUser: { id: 555 }, createdAt: at(42, 0) }),
      ]} />,
    );
    for (const id of [101, 102, 103]) expect(bubbleBox(container, id).className).toContain(MP.messageList.bubble);
    expect(bubbleBox(container, 102).className).toContain(MP.messageList.bubbleTailIn);
    expect(bubbleBox(container, 103).className).toContain(MP.messageList.bubbleTailOut);
    // Only the run's later line pulls up to 2px; a run's first line keeps the list's gap.
    expect([101, 102, 103].map((id) => line(container, id).className.split(" ").includes(MP.messageList.runGap)))
      .toEqual([false, true, false]);
    expect(timeRow(container, 101)).toBeNull();
    for (const [id, side] of [[102, "justify-start"], [103, "justify-end"]] as const) {
      const row = timeRow(container, id)!;
      for (const c of [MP.messageList.time, "text-fg-dim", side]) expect(row.className).toContain(c);
      expect(row.className).not.toMatch(/opacity-/);
    }
    // The Fan's avatar and both action rows keep the time row's room below
    // them; our avatar sits level with the time row, as the capture's.
    const room = (el: Element | null) => !!el && el.className.split(" ").includes(MP.messageList.timeRoom.split(" ")[0]);
    const actions = (id: number) => within(line(container, id)).getByRole("group", { name: "Message actions" });
    expect([room(actions(101)), room(actions(102)), room(actions(103))]).toEqual([false, true, true]);
    expect(room(line(container, 102).querySelector('[data-msg-avatar="fan"]'))).toBe(true);
    expect(room(line(container, 103).querySelector('[data-msg-avatar="creator"]'))).toBe(false);
  });
});

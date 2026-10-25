/**
 * FanRow — one Fan List row, tested at its props, which are its public
 * interface (docs/spec/phase-02-fan-list-pane.md, Testing Decisions). The
 * row is rendered from raw facts with a fixed `now`, so later row tickets
 * add their badge cases here.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { chatDraftKey } from "@/lib/chatDrafts";
import { applyTypingEvent } from "@/lib/fanTyping";
import type { OFChatItem } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { expectDomOrder } from "./composerTestHarness";
import { FanRow } from "./FanRow";
import { NOT_WIRED } from "./NotWired";

const ACCOUNT_ID = "100000001";
const FAN = { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" };
const NOW = Date.parse("2026-10-13T12:00:00Z");

const CHAT = {
  withUser: { ...FAN, avatar: null },
  lastMessage: { id: 800000001, text: "Hello there", fromUser: FAN, createdAt: "2026-10-13T11:00:00Z" },
  hasUnread: false,
  unreadMessagesCount: 0,
  __accountId: ACCOUNT_ID,
} as OFChatItem;

function renderRow(props: Partial<Parameters<typeof FanRow>[0]> = {}) {
  const callbacks = {
    onSelect: vi.fn(),
    schedulePrefetch: vi.fn(),
    cancelPrefetch: vi.fn(),
    prefetchNow: vi.fn(),
    selectedRowRef: vi.fn(),
  };
  renderWithProviders(
    <FanRow
      chat={CHAT}
      accountId={ACCOUNT_ID}
      profile={undefined}
      totalSpendCents={null}
      subscriptionStatus={null}
      expiredAt={null}
      lastPurchase={null}
      lastPpvPurchase={null}
      selected={false}
      oweDot={false}
      account={null}
      now={NOW}
      {...callbacks}
      {...props}
    />,
  );
  return callbacks;
}

const row = () => screen.getByRole("button", { name: /Fixture Fan One/ });

const HOUR = 3_600_000;
/** An ISO time `ms` before NOW (negative: after it). */
const before = (ms: number) => new Date(NOW - ms).toISOString();

/** What the row shows of the badge strip and the expired avatar. */
function badgesShown() {
  const r = row();
  return {
    New: within(r).queryByText("New", { exact: true }) !== null,
    "🔥": within(r).queryByRole("img", { name: "Bought a PPV within 7 days" }) !== null,
    "❄️": within(r).queryByRole("img", { name: "No message for over 72 hours" }) !== null,
    Off: within(r).queryByText("Off", { exact: true }) !== null,
    "❌": within(r).queryByRole("img", { name: "Subscription expired" }) !== null,
  };
}
const NONE = { New: false, "🔥": false, "❄️": false, Off: false, "❌": false };
/** A chat whose last message was sent at `createdAt`. */
const chatAt = (createdAt: string) => ({ ...CHAT, lastMessage: { ...CHAT.lastMessage!, createdAt } });

afterEach(cleanup);

describe("FanRow", () => {
  it("reads today's time as Infloww's \"7:02 pm\": numeric hour, lower case (page-parity 07 FL14)", () => {
    const at = new Date(2026, 9, 13, 19, 2);
    renderRow({ chat: chatAt(at.toISOString()), now: new Date(2026, 9, 13, 20, 0).getTime() });
    expect(within(row()).getByText("7:02 pm")).toBeInTheDocument();
  });

  it("shows an unsent draft as \"[Draft] …\" in place of the preview, except on the open chat", () => {
    sessionStorage.setItem(chatDraftKey(ACCOUNT_ID, FAN.id), "see you later");
    try {
      renderRow();
      expect(within(row()).getByText("[Draft] see you later")).toBeInTheDocument();
      expect(row()).not.toHaveTextContent("Hello there");

      cleanup();
      renderRow({ selected: true });
      expect(within(row()).queryByText(/\[Draft\]/)).not.toBeInTheDocument();
      expect(row()).toHaveTextContent("Hello there");
    } finally {
      sessionStorage.clear();
    }
  });

  it("shows \"is typing…\" in place of the preview while the Fan types", () => {
    renderRow();
    act(() => applyTypingEvent({ chat_typing: { fan_id: FAN.id }, __account_id: ACCOUNT_ID }, "chat_typing"));
    expect(row()).toHaveTextContent("is typing…");
    expect(row()).not.toHaveTextContent("Hello there");
    act(() => applyTypingEvent({ api2_chat_message: { fromUser: { id: FAN.id } }, __account_id: ACCOUNT_ID }, "api2_chat_message"));
    expect(row()).toHaveTextContent("Hello there");
  });

  it("puts aria-current=\"true\" on the selected row", () => {
    renderRow({ selected: true });
    expect(row()).toHaveAttribute("aria-current", "true");
  });

  it("leaves aria-current off an unselected row", () => {
    renderRow({ selected: false });
    expect(row()).not.toHaveAttribute("aria-current");
  });

  it("warms the Fan up on hover, focus and press, cancels on leave and blur, and selects on click", async () => {
    const cb = renderRow();

    fireEvent.mouseEnter(row());
    expect(cb.schedulePrefetch).toHaveBeenCalledTimes(1);
    expect(cb.schedulePrefetch).toHaveBeenLastCalledWith(ACCOUNT_ID, FAN.id);

    fireEvent.focus(row());
    expect(cb.schedulePrefetch).toHaveBeenCalledTimes(2);
    expect(cb.schedulePrefetch).toHaveBeenLastCalledWith(ACCOUNT_ID, FAN.id);

    fireEvent.mouseLeave(row());
    expect(cb.cancelPrefetch).toHaveBeenCalledTimes(1);
    fireEvent.blur(row());
    expect(cb.cancelPrefetch).toHaveBeenCalledTimes(2);

    fireEvent.pointerDown(row());
    expect(cb.prefetchNow).toHaveBeenCalledTimes(1);
    expect(cb.prefetchNow).toHaveBeenCalledWith(ACCOUNT_ID, FAN.id);

    expect(cb.onSelect).not.toHaveBeenCalled();
    await userEvent.click(row());
    expect(cb.onSelect).toHaveBeenCalledTimes(1);
    expect(cb.onSelect).toHaveBeenCalledWith({ accountId: ACCOUNT_ID, fanId: FAN.id, chat: CHAT });
  });

  it("marks a restricted Fan and a Fan who needs a human with their icons, and lights Off from the chat's autoRenewOff", () => {
    renderRow();
    expect(within(row()).queryByRole("img", { name: "User is restricted" })).not.toBeInTheDocument();
    expect(within(row()).queryByRole("img", { name: "Needs human" })).not.toBeInTheDocument();
    expect(badgesShown()).toEqual(NONE);

    cleanup();
    renderRow({ chat: { ...CHAT, withUser: { ...CHAT.withUser, isRestricted: true, needsHuman: true, autoRenewOff: true } } });
    expect(within(row()).getByRole("img", { name: "User is restricted" })).toBeInTheDocument();
    expect(within(row()).getByRole("img", { name: "Needs human" })).toBeInTheDocument();
    expect(badgesShown()).toEqual({ ...NONE, Off: true });
  });

  it("in select mode a click toggles the pick and does not open the chat; aria-pressed follows the pick", async () => {
    const onTogglePick = vi.fn();
    const cb = renderRow({ onTogglePick, picked: false });
    expect(row()).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(row());
    expect(onTogglePick).toHaveBeenCalledTimes(1);
    expect(cb.onSelect).not.toHaveBeenCalled();

    cleanup();
    renderRow({ onTogglePick, picked: true });
    expect(row()).toHaveAttribute("aria-pressed", "true");

    cleanup();
    renderRow();
    expect(row()).not.toHaveAttribute("aria-pressed");
  });

  it("shows the owe dot only when the row is told to show it", () => {
    // CHAT is read and the Fan wrote last, so it owes a reply either way.
    renderRow({ oweDot: false });
    expect(screen.queryByRole("img", { name: "Read · awaiting your reply" })).not.toBeInTheDocument();

    cleanup();
    renderRow({ oweDot: true });
    expect(screen.getByRole("img", { name: "Read · awaiting your reply" })).toBeInTheDocument();
  });

  it("shows the online dot when the Fan is online, and not otherwise", () => {
    renderRow({ chat: { ...CHAT, isOnline: true } });
    expect(within(row()).getByRole("img", { name: "Online" })).toBeInTheDocument();

    cleanup();
    renderRow({ chat: { ...CHAT, isOnline: false } });
    expect(screen.queryByRole("img", { name: "Online" })).not.toBeInTheDocument();
  });

  it("rings the online dot in the row's background: the pane, the hover fill, the selected fill", () => {
    // Spec Story 3: "ringed in the row's background (selected and hovered too)".
    renderRow({ chat: { ...CHAT, isOnline: true } });
    let dot = within(row()).getByRole("img", { name: "Online" });
    expect(dot).toHaveClass("border-[var(--inf-pane,var(--color-panel))]");
    // A hovered row fills `bg-bg-elev-1` (the palette's hover grey); the ring follows it.
    expect(row()).toHaveClass("group", "hover:bg-bg-elev-1");
    expect(dot).toHaveClass("group-hover:border-bg-elev-1");

    cleanup();
    renderRow({ selected: true, chat: { ...CHAT, isOnline: true } });
    dot = within(row()).getByRole("img", { name: "Online" });
    expect(row()).toHaveClass("bg-[var(--inf-row-selected,var(--color-bg-elev-1))]");
    expect(dot).toHaveClass("border-[var(--inf-row-selected,var(--color-bg-elev-1))]", "group-hover:border-bg-elev-1");
  });

  it("draws the avatar circle in its own grey, never the selected row's fill, with light initials", () => {
    // Ticket 151 visual loop: on the selected row the circle took the row's
    // #353535 and vanished; the capture's circle is #666666 on either row (Compare FL1).
    renderRow({ selected: true });
    const circle = within(row()).getByText("FI").parentElement!;
    expect(circle).toHaveClass("bg-[var(--inf-list-avatar,var(--color-bg-elev-2))]");
    expect(circle.className).not.toMatch(/inf-row-selected/);
    expect(within(row()).getByText("FI")).toHaveClass("text-fg");
  });

  it("marks an unread row with the 9px unread dot and a bold preview, and a muted row with the mute icon and no dimming", () => {
    // Read row first: the preview is not bold and there is no unread dot.
    renderRow();
    expect(screen.getByText("Hello there")).not.toHaveClass("font-semibold");
    expect(screen.queryByRole("img", { name: /^Unread/ })).not.toBeInTheDocument();

    cleanup();
    renderRow({ chat: { ...CHAT, hasUnread: true, unreadMessagesCount: 3 } });
    const dot = within(row()).getByRole("img", { name: "Unread (3)" });
    expect(dot).toHaveAttribute("title", "Unread (3)");
    // The count lives in the tooltip; the old 18px count badge is gone.
    expect(within(row()).queryByText("3")).not.toBeInTheDocument();
    expect(screen.getByText("Hello there")).toHaveClass("font-semibold");

    cleanup();
    renderRow({ chat: { ...CHAT, isMutedNotifications: true } });
    expect(within(row()).getByRole("img", { name: "Muted notifications" })).toBeInTheDocument();
    expect(row().querySelector("[class*='opacity-']")).toBeNull();
    expect(row().className).not.toMatch(/opacity-/);
  });

  it("puts \"last buy …\" and \"renews/ends …\" in the row's tooltip and draws only two lines", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    try {
      // No facts: no tooltip.
      renderRow();
      expect(row()).not.toHaveAttribute("title");

      cleanup();
      renderRow({
        totalSpendCents: 4200,
        lastPurchase: "2026-10-13T09:00:00Z",
        subscriptionStatus: "active",
        expiredAt: "2026-10-18T12:00:00Z",
      });
      expect(row()).toHaveAttribute("title", "$42 · last buy 3h ago · renews in 5d");
      // Line one: the name and @handle. Line two: the preview and time.
      expect(within(row()).getByText("Fixture Fan One")).toBeInTheDocument();
      expect(within(row()).getByText("@fixturefanone")).toBeInTheDocument();
      expect(within(row()).getByText("Hello there")).toBeInTheDocument();
      // No third line: "last buy" and "renews" are only in the tooltip, and
      // the spend shows once, as the pill under the avatar (ticket 137).
      expect(within(row()).getAllByText(/\$42/)).toEqual([within(row()).getByText("$42", { exact: true })]);
      expect(row()).not.toHaveTextContent("last buy");
      expect(row()).not.toHaveTextContent("renews");

      cleanup();
      renderRow({
        lastPurchase: null,
        subscriptionStatus: "set to expire",
        expiredAt: "2026-10-18T12:00:00Z",
      });
      expect(row()).toHaveAttribute("title", "ends in 5d");
      expect(row()).not.toHaveTextContent("ends in 5d");
    } finally {
      vi.useRealTimers();
    }
  });

  it("lights New, 🔥, ❄️ and Off each on its own, New and 🔥 through exactly 7×24h and ❄️ only past 72h, and a missing, unparseable or future time lights nothing", () => {
    // The base row: a message 1h ago, no subscribe time, no PPV, no subscription.
    renderRow();
    expect(badgesShown()).toEqual(NONE);

    const cases: Array<[string, Partial<Parameters<typeof FanRow>[0]>, typeof NONE]> = [
      // New: subscribed within 7×24h, inclusive.
      ["subscribed exactly 7×24h ago", { subscribedAt: before(7 * 24 * HOUR) }, { ...NONE, New: true }],
      ["subscribed 1s past 7×24h", { subscribedAt: before(7 * 24 * HOUR + 1000) }, NONE],
      ["subscribed an hour from now", { subscribedAt: before(-HOUR) }, NONE],
      ["an unparseable subscribe time", { subscribedAt: "not a date" }, NONE],
      // 🔥: the last PPV purchase within 7×24h, inclusive.
      ["a PPV an hour ago", { lastPpvPurchase: before(HOUR) }, { ...NONE, "🔥": true }],
      ["a PPV exactly 7×24h ago", { lastPpvPurchase: before(7 * 24 * HOUR) }, { ...NONE, "🔥": true }],
      ["a PPV 1s past 7×24h", { lastPpvPurchase: before(7 * 24 * HOUR + 1000) }, NONE],
      ["a PPV an hour from now", { lastPpvPurchase: before(-HOUR) }, NONE],
      ["an unparseable PPV time", { lastPpvPurchase: "not a date" }, NONE],
      // ❄️: the last message is more than 72h old.
      ["last message exactly 72h ago", { chat: chatAt(before(72 * HOUR)) }, NONE],
      ["last message 1s past 72h", { chat: chatAt(before(72 * HOUR + 1000)) }, { ...NONE, "❄️": true }],
      ["last message an hour from now", { chat: chatAt(before(-HOUR)) }, NONE],
      ["an unparseable last message time", { chat: chatAt("not a date") }, NONE],
      ["no message at all", { chat: { ...CHAT, lastMessage: undefined } }, NONE],
      // Off: renewal off and not expired.
      ["renewal off, ending in 5 days", { subscriptionStatus: "Set to Expire", expiredAt: before(-5 * 24 * HOUR) },
        { ...NONE, Off: true }],
      ["renewing, in 5 days", { subscriptionStatus: "active", expiredAt: before(-5 * 24 * HOUR) }, NONE],
    ];
    for (const [label, props, shown] of cases) {
      cleanup();
      renderRow(props);
      expect({ label, ...badgesShown() }).toEqual({ label, ...shown });
    }

    // All four lit together read New, 🔥, ❄️, Off, in that order, after the name and @handle.
    cleanup();
    renderRow({
      subscribedAt: before(HOUR),
      lastPpvPurchase: before(HOUR),
      chat: chatAt(before(100 * HOUR)),
      subscriptionStatus: "Set to Expire",
      expiredAt: before(-5 * 24 * HOUR),
    });
    const order = [
      within(row()).getByText("Fixture Fan One"),
      within(row()).getByText("@fixturefanone"),
      within(row()).getByText("New", { exact: true }),
      within(row()).getByRole("img", { name: "Bought a PPV within 7 days" }),
      within(row()).getByRole("img", { name: "No message for over 72 hours" }),
      within(row()).getByText("Off", { exact: true }),
    ];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("turns an expired Fan's avatar into the red ✕, without \"Off\" even when renewal is off", () => {
    // Renewal off and expired a day ago: the ✕ avatar, and no "Off".
    renderRow({ subscriptionStatus: "Set to Expire", expiredAt: before(24 * HOUR) });
    expect(badgesShown()).toEqual({ ...NONE, "❌": true });
    const mark = within(row()).getByRole("img", { name: "Subscription expired" });
    expect(mark).toHaveClass("bg-err");
    // The ✕ takes the avatar's place: the initials are gone.
    expect(within(row()).queryByText("FI")).not.toBeInTheDocument();

    // The same Fan a day before expiry: the plain avatar and "Off".
    cleanup();
    renderRow({ subscriptionStatus: "Set to Expire", expiredAt: before(-24 * HOUR) });
    expect(badgesShown()).toEqual({ ...NONE, Off: true });

    // Expired whatever the status says; an unparseable expiry expires nothing.
    cleanup();
    renderRow({ subscriptionStatus: "active", expiredAt: before(1000) });
    expect(badgesShown()).toEqual({ ...NONE, "❌": true });
    cleanup();
    renderRow({ subscriptionStatus: "active", expiredAt: "not a date" });
    expect(badgesShown()).toEqual(NONE);

    // Expiry is read against the row's `now`, not the clock: with the clock
    // 30 days on, a Fan whose renewal is off and who ends a day after `now`
    // still reads "Off".
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW + 30 * 24 * HOUR);
    try {
      cleanup();
      renderRow({ subscriptionStatus: "Set to Expire", expiredAt: before(-24 * HOUR) });
      expect(badgesShown()).toEqual({ ...NONE, Off: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a spender's avatar with the Total spend in a pill under it, \"$0\" for a known zero, an expired spender's \"$N\" under the ✕, and no pill while spend is unknown", () => {
    // A Fan with a photo, so "no avatar image" can fail.
    const withPhoto = { ...CHAT, withUser: { ...CHAT.withUser, avatar: "https://cdn.example.invalid/fan.jpg" } };
    const photo = () => within(row()).queryByRole("presentation");

    // A spender: the photo stays, and the orange "$45" pill is the only figure.
    renderRow({ chat: withPhoto, totalSpendCents: 4_500 });
    expect(photo()).toBeInTheDocument();
    expect(within(row()).getByText("$45", { exact: true })).toHaveClass("text-warn");
    expect(within(row()).getAllByText(/^\$/)).toHaveLength(1);

    // A known zero: the photo, and "$0" in the same orange pill, as Infloww.
    cleanup();
    renderRow({ chat: withPhoto, totalSpendCents: 0 });
    expect(photo()).toBeInTheDocument();
    expect(within(row()).getByText("$0", { exact: true })).toHaveClass("text-warn");

    // An expired spender: the ✕ avatar, and the spend in the orange pill.
    cleanup();
    renderRow({ chat: withPhoto, totalSpendCents: 23_000, subscriptionStatus: "Set to Expire", expiredAt: before(24 * HOUR) });
    expect(within(row()).getByRole("img", { name: "Subscription expired" })).toBeInTheDocument();
    expect(within(row()).getByText("$230", { exact: true })).toHaveClass("text-warn");
    expect(photo()).not.toBeInTheDocument();

    // An expired Fan with a known zero: the ✕ avatar and "$0".
    cleanup();
    renderRow({ chat: withPhoto, totalSpendCents: 0, subscriptionStatus: "Set to Expire", expiredAt: before(24 * HOUR) });
    expect(within(row()).getByRole("img", { name: "Subscription expired" })).toBeInTheDocument();
    expect(within(row()).getByText("$0", { exact: true })).toHaveClass("text-warn");

    // Unknown spend (spend-batch loading, or no entry for the Fan): the photo and no pill.
    cleanup();
    renderRow({ chat: withPhoto, totalSpendCents: null });
    expect(photo()).toBeInTheDocument();
    expect(within(row()).queryByText(/^\$/)).not.toBeInTheDocument();

    // Without a photo, a spender keeps the initials, with the pill.
    cleanup();
    renderRow({ totalSpendCents: 4_500 });
    expect(within(row()).getByText("FI")).toBeInTheDocument();
    expect(within(row()).getByText("$45", { exact: true })).toBeInTheDocument();
  });

  it("shows the verified badge between the name and the @handle when the chat's user or the cached profile says verified, and none otherwise", () => {
    const verified = () => within(row()).queryByRole("img", { name: "Verified" });

    renderRow({ chat: { ...CHAT, withUser: { ...CHAT.withUser, isVerified: true } } });
    expect(verified()).toBeInTheDocument();
    expectDomOrder([within(row()).getByText("Fixture Fan One"), verified()!, within(row()).getByText("@fixturefanone")]);

    cleanup();
    renderRow({ profile: { ...FAN, isVerified: true } });
    expect(verified()).toBeInTheDocument();

    cleanup();
    renderRow({ profile: { ...FAN } });
    expect(verified()).not.toBeInTheDocument();

    cleanup();
    renderRow({ chat: { ...CHAT, withUser: { ...CHAT.withUser, isVerified: false } }, profile: { ...FAN, isVerified: false } });
    expect(verified()).not.toBeInTheDocument();
  });

  it("ends line one in a muted ✕ named \"Not wired\" whose click shows its excuse and neither selects the row nor warms the Fan", async () => {
    const cb = renderRow({ subscriptionStatus: "Set to Expire", expiredAt: before(-5 * 24 * HOUR) });
    const x = within(row()).getByRole("img", { name: "Not wired" });
    expect(x).toHaveAttribute("title", `not wired: ${NOT_WIRED.rowClose}`);
    expect(x).toHaveClass("text-fg-dim");
    // After the handle and the badges.
    expectDomOrder([within(row()).getByText("@fixturefanone"), within(row()).getByText("Off", { exact: true }), x]);

    fireEvent.pointerDown(x);
    await userEvent.click(x);
    expect(within(row()).getByRole("status")).toHaveTextContent(NOT_WIRED.rowClose);
    expect(cb.onSelect).not.toHaveBeenCalled();
    expect(cb.prefetchNow).not.toHaveBeenCalled();
  });

  it("shows the muted bell after the time on a muted row, unread or not", () => {
    renderRow({ chat: { ...CHAT, hasUnread: true, unreadMessagesCount: 2, isMutedNotifications: true } });
    const bell = within(row()).getByRole("img", { name: "Muted notifications" });
    expectDomOrder([within(row()).getByText("Hello there"), bell]);
    expect(within(row()).getByRole("img", { name: "Unread (2)" })).toBeInTheDocument();

    cleanup();
    renderRow({ chat: { ...CHAT, isMutedNotifications: true }, oweDot: true });
    expect(within(row()).getByRole("img", { name: "Muted notifications" })).toBeInTheDocument();
  });

  it("draws the unread and owe dots as Edge markers off the preview line, and unread wins over owe", () => {
    const previewLine = () => within(row()).getByText("Hello there").parentElement!;

    renderRow({ chat: { ...CHAT, hasUnread: true, unreadMessagesCount: 1 } });
    const unread = within(row()).getByRole("img", { name: "Unread (1)" });
    expect(previewLine()).not.toContainElement(unread);

    cleanup();
    renderRow({ oweDot: true });
    const owe = within(row()).getByRole("img", { name: "Read · awaiting your reply" });
    expect(previewLine()).not.toContainElement(owe);

    cleanup();
    renderRow({ chat: { ...CHAT, hasUnread: true, unreadMessagesCount: 1 }, oweDot: true });
    expect(within(row()).getByRole("img", { name: "Unread (1)" })).toBeInTheDocument();
    expect(within(row()).queryByRole("img", { name: "Read · awaiting your reply" })).not.toBeInTheDocument();
  });

  it("reads a Total spend above $9,999 in \"k\" and a smaller one in whole dollars", () => {
    const cases: Array<[number, string]> = [
      [999_900, "$9,999"],
      [999_949, "$9,999"],
      [999_950, "$10k"],
      [1_000_000, "$10k"],
      [1_248_000, "$12.5k"],
      [4_250, "$43"],
      [100, "$1"],
    ];
    for (const [cents, shown] of cases) {
      cleanup();
      renderRow({ totalSpendCents: cents });
      expect({ cents, shown: within(row()).getByText(/^\$/).textContent }).toEqual({ cents, shown });
    }
  });

  describe("right-click menu", () => {
    /** The Fan's Deep link in a Pop-out window (spec, Rows; Phase 0). */
    const POPOUT_HREF = "/messages-pro/100000001/200000001";
    const openItem = () => screen.queryByRole("button", { name: "Open in a new window" });
    let windowOpen: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      windowOpen = vi.spyOn(window, "open").mockImplementation(() => null);
    });
    afterEach(() => windowOpen.mockRestore());

    it("offers \"Open in a new window\" on right-click, which opens the Fan's Deep link as a Pop-out window and closes", async () => {
      const cb = renderRow();
      expect(openItem()).toBeNull();

      // The browser's own context menu is suppressed.
      expect(fireEvent.contextMenu(row())).toBe(false);
      await userEvent.click(openItem()!);

      expect(windowOpen).toHaveBeenCalledTimes(1);
      expect(windowOpen).toHaveBeenCalledWith(POPOUT_HREF, "_blank", "popup");
      expect(openItem()).toBeNull();
      expect(cb.onSelect).not.toHaveBeenCalled();
    });

    it("closes on Escape and on a press outside without opening anything", async () => {
      renderRow();
      fireEvent.contextMenu(row());
      expect(openItem()).toBeInTheDocument();
      await userEvent.keyboard("{Escape}");
      expect(openItem()).toBeNull();

      fireEvent.contextMenu(row());
      expect(openItem()).toBeInTheDocument();
      fireEvent.pointerDown(document.body);
      expect(openItem()).toBeNull();

      expect(windowOpen).not.toHaveBeenCalled();
    });

    it("leaves a left click selecting the row, with no menu", async () => {
      const cb = renderRow();
      await userEvent.click(row());
      expect(cb.onSelect).toHaveBeenCalledTimes(1);
      expect(cb.onSelect).toHaveBeenCalledWith({ accountId: ACCOUNT_ID, fanId: FAN.id, chat: CHAT });
      expect(openItem()).toBeNull();
      expect(windowOpen).not.toHaveBeenCalled();
    });
  });
});

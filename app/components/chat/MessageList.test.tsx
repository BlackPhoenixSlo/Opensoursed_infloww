/**
 * MessageList — bubble-side stability (T0 / DA bugs 8 & 12).
 *
 * The "all-left-then-spread" flash came from deriving each bubble's side
 * from the async `/users/me` owner id, which is null on first paint. These
 * tests pin the two replacement signals:
 *   • side-from-direction (bug 12): a DB-seeded row carries an explicit
 *     `_side` off the authoritative `direction` column, so it aligns
 *     correctly even when `ownerUserId` is still null.
 *   • side-from-cache (bug 8): a live OF row (no `_side`) aligns on the
 *     FIRST render when the owner id is supplied synchronously (in the app,
 *     ChatSurface hydrates it from the `of-owner:<acct>` localStorage cache).
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, waitFor, within } from "@testing-library/react";

// The reply-strip harness renders the real Composer, so the relay is mocked by
// URL (Phase 4's Seam 1 harness).
vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));

import { renderWithProviders } from "@/test-utils";
import { MP } from "@/lib/messagesPro";
import { relayGet, relayPost } from "./composerTestHarness";
import { baseProps, bubbleBox, msg, timeRow, type SeedMsg } from "./messageListTestHarness";
import { dateDividerLabel, MessageList, messageRuns, newestReadPointer } from "@/components/chat/MessageList";
import { withdrawnLines } from "@/lib/withdrawnLines";
import { Composer } from "@/components/chat/Composer";
import { quoteFromMessage, type QuotedReply } from "@/components/chat/ReplyStrip";
import type { OFMessage } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";

/** The bubble box's side-specific background: `bg-accent` (outgoing/right)
 *  vs the Fan's bubble, Infloww's grey inside Messages Pro and
 *  `--color-bg-elev-1` anywhere else (left). */
const INCOMING = "bg-[var(--inf-bubble-in,var(--color-bg-elev-1))]";

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
});

describe("MessageList bubble alignment", () => {
  it("side-from-direction: a DB-seeded row aligns by `direction` even when ownerUserId is null", () => {
    const messages = [
      msg({ id: 1, text: "we sent this", fromUser: { id: 777 }, _side: "right" }),
      msg({ id: 2, text: "fan sent this", fromUser: { id: 42 }, _side: "left" }),
    ];

    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={messages} ownerUserId={null} />,
    );

    const out = bubbleBox(container, 1);
    const inc = bubbleBox(container, 2);
    // `_side` drives it — no id comparison, no dependence on ownerUserId.
    expect(out.className).toContain("bg-accent");
    expect(out.className).not.toContain(INCOMING);
    expect(inc.className).toContain(INCOMING);
    expect(inc.className).not.toContain("bg-accent");
  });

  it("side-from-cache: a live row (no _side) aligns right on the FIRST render when the owner id is synchronous", () => {
    // ChatSurface persists the resolved /users/me id here and re-reads it
    // synchronously on the next mount. Simulate that warm cache.
    window.localStorage.setItem("of-owner:acct1", "555");
    const ownerUserId = Number(window.localStorage.getItem("of-owner:acct1"));

    const messages = [
      msg({ id: 10, text: "live outbound", fromUser: { id: 555 } }), // live OF row, no _side
      msg({ id: 11, text: "live inbound", fromUser: { id: 42 } }),
    ];

    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={messages} ownerUserId={ownerUserId} />,
    );

    // No waitFor: a synchronous owner id means the very first paint is
    // already correctly sided (the whole point of the cache).
    expect(bubbleBox(container, 10).className).toContain("bg-accent");
    expect(bubbleBox(container, 11).className).toContain(INCOMING);
  });

  it("side-from-cache control: without an owner id, a live row defaults left (the old flash state)", () => {
    const messages = [msg({ id: 20, text: "live outbound", fromUser: { id: 555 } })];

    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={messages} ownerUserId={null} />,
    );

    // This is exactly the case the synchronous cache fixes: with no owner
    // id and no _side there is nothing to align against, so it falls left.
    expect(bubbleBox(container, 20).className).toContain(INCOMING);
  });
});

// The PPV status line reads paid on EITHER OF's `isOpened` OR our ledger's
// `isPaid`. is_paid lands minutes before OF's isOpened echoes on a fresh
// fetch, so a purchased PPV must not linger "not paid" on a cached bubble.
describe("MessageList PPV unlock (isOpened || isPaid)", () => {
  function ppv(over: Partial<SeedMsg>): OFMessage {
    // Inbound, as a Fan's PPV: the status line and the 🔒 tile render.
    return msg({ id: 30, text: "", price: 29.99, _side: "left",
      fromUser: { id: 42 }, ...over });
  }

  it("not paid when neither isOpened nor isPaid is set", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[ppv({ isOpened: false, isPaid: false })]} ownerUserId={555} />,
    );
    expect(container.textContent).toContain("$29.99 · not paid");
  });

  it("paid on the ledger's isPaid alone, even when OF still reports isOpened=false", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[ppv({ isOpened: false, isPaid: true })]} ownerUserId={555} />,
    );
    expect(container.textContent).toContain("$29.99 · paid");
    expect(container.textContent).not.toContain("not paid");
  });

  it("paid on OF's isOpened alone (the pre-existing path still works)", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[ppv({ isOpened: true })]} ownerUserId={555} />,
    );
    expect(container.textContent).toContain("$29.99 · paid");
    expect(container.textContent).not.toContain("not paid");
  });
});

// The Creator's side never shows the Fan's "UNLOCK FOR $X" bar. The PPV card
// ends in one status line instead, as the old Infloww overlay's `.ppv-mini`
// did: title, media, then "$X.XX · paid" / "$X.XX · not paid" inside the card
// (the deleted Clone's messages.js:885-890, tag legacy-ui-final).
describe("MessageList PPV price line in the card", () => {
  function sent(over: Partial<SeedMsg>): OFMessage {
    return msg({ id: 31, text: "", price: 35, _side: "right", fromUser: { id: 555 }, ...over });
  }
  /** The bubble's column: the bubble box and its siblings (time row). */
  const column = (container: HTMLElement, id: number) => bubbleBox(container, id).parentElement!;

  it("an unpaid PPV we sent shows no unlock bar, and one '$35.00 · not paid' line inside its card", () => {
    const { container, queryByRole } = renderWithProviders(
      <MessageList {...baseProps} messages={[sent({ isOpened: false, isPaid: false })]} ownerUserId={555} />,
    );
    expect(container.textContent).not.toMatch(/unlock for/i);
    expect(queryByRole("button", { name: /unlock/i })).toBeNull();
    expect(bubbleBox(container, 31).textContent).toContain("$35.00 · not paid");
    expect(column(container, 31).textContent!.split("· not paid").length - 1).toBe(1);
  });

  it("a paid PPV we sent reads '$29.99 · paid' inside its card", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[sent({ price: 29.99, isPaid: true })]} ownerUserId={555} />,
    );
    expect(bubbleBox(container, 31).textContent).toContain("$29.99 · paid");
    expect(container.textContent).not.toContain("not paid");
    expect(container.textContent).not.toMatch(/unlock for/i);
  });
});

/**
 * A failed refresh must not delete the conversation.
 *
 * A fan who deletes his OnlyFans account 404s on every poll, forever. The
 * error branch used to return a full-pane "Failed to load: upstream 404:
 * {"error":{"code":0,"message":"User not found"}}" — blanking a thread whose
 * cached copy was, at that point, the only one left anywhere.
 */
describe("load errors never hide cached history", () => {
  const err = new Error('upstream 404: {"error":{"code":0,"message":"User not found"}}');

  it("keeps rendering cached messages when the refresh 404s", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        isError
        error={err}
        messages={[msg({ id: 1, text: "cached line" })]}
        ownerUserId={555}
      />,
    );
    expect(container.textContent).toContain("cached line");
  });

  it("shows the failure as a notice above the thread, not instead of it", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        isError
        error={err}
        messages={[msg({ id: 1, text: "cached line" })]}
        ownerUserId={555}
      />,
    );
    const notice = container.querySelector('[role="status"]');
    expect(notice).not.toBeNull();
    // Plain-language, and it does NOT leak the raw upstream json at the operator.
    expect(notice!.textContent).toContain("no longer exists");
    expect(container.textContent).not.toContain('{"error"');
    // `sticky`, never `absolute` — an absolute banner would cover message #1.
    expect(notice!.className).toContain("sticky");
  });

  it("still blocks with the error when there is nothing cached to show", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} isError error={err} messages={[]} ownerUserId={555} />,
    );
    expect(container.textContent).toContain("no longer exists");
  });

  it("distinguishes transient failures, because those ARE worth retrying", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        isError
        error={new Error("upstream timeout: ...")}
        messages={[]}
        ownerUserId={555}
      />,
    );
    expect(container.textContent).toContain("timed out");
    expect(container.textContent).not.toContain("no longer exists");
  });
});

/**
 * A failed media send: OF names the offending attachment in
 * `payload.removeFromInputMediaIds`, `useSendMessage` parks it on the bubble as
 * `_failedMediaIds`, and the bubble has to point AT it. On 2026-08-16 the same
 * item was re-picked into three bundles because the footer only ever repeated
 * OF's sentence, which says "media" without saying which.
 */
describe("MessageList refused-attachment marking", () => {
  // jsdom has no IntersectionObserver and MediaTile's lazy path constructs one
  // on mount — these are the only cases here that render tiles at all.
  class IOStub {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): unknown[] {
      return [];
    }
  }
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", IOStub);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** A failed send of `count` attachments, with the ids at `refusedIdx`
   *  refused. Parameterised on purpose: the first version of these tests
   *  hard-coded TWO tiles, which is under IMAGE_CAP=3, so `items.slice(0, cap)`
   *  could never truncate and the assertions passed no matter what the render
   *  cap did. The incident that produced the feature was a FOUR-media bundle —
   *  the shape the parser test already encodes and the render test could not
   *  express. */
  const failedSend = (count: number, refusedIdx: number[], over: Partial<SeedMsg> = {}): OFMessage => {
    const media = Array.from({ length: count }, (_, i) => ({
      id: 3000000000 + i,
      type: "video",
      files: { thumb: { url: `https://cdn/${i}.jpg` } },
    }));
    return msg({
      id: -1,
      _tempId: -1,
      _failed: true,
      _failedReason: "Something wrong with attached media, please try to upload it again",
      _failedMediaIds: refusedIdx.map((i) => 3000000000 + i),
      text: "sparing",
      price: 144,
      fromUser: { id: 555 },
      media,
      ...over,
    } as Partial<SeedMsg> & { id: number });
  };

  const marks = (c: HTMLElement) =>
    c.querySelectorAll("div[title^='This attachment was refused']");

  it("counts the refused attachments beside the tiles", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(2, [1])]} ownerUserId={555} />,
    );
    expect(container.textContent).toContain("remove 1 of 2");
  });

  it("marks the tile OF named and leaves its neighbour alone", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(2, [1])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(1);
    expect(marks(container)[0].textContent).toContain("REMOVE");
  });

  it("marks a refused tile that sits PAST the 3-tile render cap", () => {
    // The incident's own shape. Before the fix the row rendered 3 tiles + a
    // "+1" pill, the footer claimed "remove 1 of 4", and nothing was marked.
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(4, [3])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(1);
    expect(container.textContent).toContain("remove 1 of 4");
    // Force-opened, so no tile is hidden behind a pill that carries no warning.
    expect(container.textContent).not.toContain("+1");
  });

  it("marks BOTH when OF names one visible and one hidden tile", () => {
    // One mark beside a count of two is worse than none: it reads as a complete
    // answer, so the operator drops that tile and fails identically on the other.
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(4, [1, 3])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(2);
    expect(container.textContent).toContain("remove 2 of 4");
  });

  it("never claims a count it cannot point at", () => {
    // OF naming an id this bubble does not hold (a fresh-claim upload whose
    // vault id only exists server-side). The count is an intersection, so it
    // stays silent rather than printing a number over an unmarked row.
    const stray = failedSend(2, [], { _failedMediaIds: [999999999] });
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[stray]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(0);
    expect(container.textContent).not.toContain("remove");
    // OF's own sentence still reaches the operator.
    expect(container.textContent).toContain("Something wrong with attached media");
  });

  it("marks a hidden refusal that arrives AFTER the bubble mounted", () => {
    // THE LIVE ORDERING, which every other fixture here skips. `sendNow` calls
    // appendLocal synchronously, so MediaStrip mounts on the PENDING bubble
    // with no `_failedMediaIds`; `failLocal` then patches the same row in place
    // — same id, same React key, same instance. A force-open read once at mount
    // is therefore always read too early, and the feature silently does nothing
    // on the only path that produces a refusal.
    const pending = failedSend(4, [], { _failed: false, _pending: true, _failedReason: undefined });
    const { container, rerender } = renderWithProviders(
      <MessageList {...baseProps} messages={[pending]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(0);
    expect(container.textContent).toContain("+1");

    rerender(
      <MessageList {...baseProps} messages={[failedSend(4, [3])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(1);
    expect(container.textContent).toContain("remove 1 of 4");
    expect(container.textContent).not.toContain("+1");
  });

  it("collapses again once a retry clears the failure", () => {
    // The other direction: derived-once state would leave the row pinned open
    // with the marks gone after `retry()` re-appends under the same tempId.
    const { container, rerender } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(4, [3])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(1);

    const retried = failedSend(4, [], { _failed: false, _pending: true, _failedReason: undefined });
    rerender(<MessageList {...baseProps} messages={[retried]} ownerUserId={555} />);
    expect(marks(container).length).toBe(0);
    expect(container.textContent).toContain("+1");
  });

  it("a collapse taken BEFORE the failure cannot hide the mark", () => {
    // The operator peeks at a big bundle and collapses it again while the POST
    // is still in flight, then the failure lands. A stored click that outranked
    // the refusal made this render zero marks under "remove 1 of 6" — the third
    // variant of the same defect, re-entered through the operator's own hand.
    const pending = failedSend(6, [], { _failed: false, _pending: true, _failedReason: undefined });
    const { container, rerender } = renderWithProviders(
      <MessageList {...baseProps} messages={[pending]} ownerUserId={555} />,
    );
    fireEvent.click(container.querySelector("button")!);            // "+3"
    const less = [...container.querySelectorAll("button")]
      .find((b) => b.textContent?.includes("show less"));
    if (less) fireEvent.click(less);

    rerender(
      <MessageList {...baseProps} messages={[failedSend(6, [5])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(1);
    expect(container.textContent).toContain("remove 1 of 6");
    expect(container.textContent).not.toContain("+3");
  });

  it("keeps a refused tile in the COLLAPSED set, and still collapses", () => {
    // The guarantee that replaced three attempts at a force-open flag: the
    // marked tile is in view because the collapsed slice includes it by
    // membership, not because a boolean forced the row open. So the row still
    // behaves like any other — "+N", "show less" — and no click can hide the mark.
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(6, [5])]} ownerUserId={555} />,
    );
    // 3 by position + the refused one pulled forward, 2 still behind the pill.
    expect(marks(container).length).toBe(1);
    expect(container.textContent).toContain("+2");

    const pill = [...container.querySelectorAll("button")]
      .find((b) => b.textContent?.trim() === "+2")!;
    fireEvent.click(pill);
    expect(container.textContent).not.toContain("+2");
    const less = [...container.querySelectorAll("button")]
      .find((b) => b.textContent?.includes("show less"))!;
    expect(less).toBeTruthy();

    fireEvent.click(less);
    // Collapsed again — and the mark survived the round trip.
    expect(container.textContent).toContain("+2");
    expect(marks(container).length).toBe(1);
  });

  it("collapses a huge bundle even when its last item is the refused one", () => {
    // The case the 3-tile cap exists for. A force-open rendered all 40 with no
    // control at all, on a bubble that cannot be retried away or dismissed.
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[failedSend(40, [39])]} ownerUserId={555} />,
    );
    expect(marks(container).length).toBe(1);
    expect(container.textContent).toContain("+36");
    expect(container.querySelectorAll("a[href]").length).toBe(4);
  });

  it("says nothing extra when the failure is not about media", () => {
    const noIds = failedSend(2, [], { _failedMediaIds: undefined });
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[noIds]} ownerUserId={555} />,
    );
    expect(container.textContent).toContain("failed — retry");
    expect(container.textContent).not.toContain("remove");
    expect(marks(container).length).toBe(0);
  });
});

/**
 * A landed co-performer tag. The bubble renders `releaseForms` — what OF
 * STORED — so an operator can tell a tag that stuck from one OF dropped. Until
 * 2026-08-17 the chat body sent its ids in `userTags`, which that endpoint
 * ignores, and nothing rendered the field: the send looked identical either way.
 */
describe("MessageList release-form tags", () => {
  it("names the tagged co-performer on the bubble", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[
          msg({
            id: 7,
            text: "collab",
            fromUser: { id: 555 },
            releaseForms: [{ id: 424242, name: "Ava Rae", type: "user", partnerSource: "tag" }],
          } as Partial<SeedMsg> & { id: number }),
        ]}
        ownerUserId={555}
      />,
    );
    expect(container.textContent).toContain("Ava Rae");
  });

  it("shows nothing when OF stored no tag, however the send was composed", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[msg({ id: 8, text: "collab", fromUser: { id: 555 }, releaseForms: [] })]}
        ownerUserId={555}
      />,
    );
    expect(container.querySelector("[title^='Tagged on OnlyFans']")).toBeNull();
  });
});

/**
 * Phase 3 ticket 98 (spec gap row L4, F28): our bubbles carry a glyph receipt
 * in the time row, ✓ "Delivered" or ✓✓ "Seen" by the Fan's read pointer, and
 * the Thread takes the newer of two read pointers.
 */
describe("MessageList receipts and the read pointer", () => {
  it("shows ✓✓ named 'Seen' at or before the read pointer and ✓ named 'Delivered' after it", () => {
    const { container, getAllByRole, getByRole } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[
          msg({ id: 50, text: "older", fromUser: { id: 555 }, createdAt: "2026-06-04T12:00:00.000Z" }),
          msg({ id: 51, text: "read", fromUser: { id: 555 }, createdAt: "2026-06-04T12:01:00.000Z" }),
          msg({ id: 52, text: "newer", fromUser: { id: 555 }, createdAt: "2026-06-04T12:02:00.000Z" }),
        ]}
        ownerUserId={555}
        lastReadByPeerId={51}
      />,
    );
    const seen = getAllByRole("img", { name: "Seen" });
    expect(seen).toHaveLength(2);
    for (const [i, id] of [50, 51].entries()) {
      expect(seen[i].textContent).toBe("✓✓");
      expect(seen[i].getAttribute("title")).toBe("Seen");
      expect(timeRow(container, id)!.contains(seen[i])).toBe(true);
    }
    const delivered = getByRole("img", { name: "Delivered" });
    expect(delivered.textContent).toBe("✓");
    expect(delivered.getAttribute("title")).toBe("Delivered");
    expect(timeRow(container, 52)!.contains(delivered)).toBe(true);
    // Glyphs only: the words no longer show.
    expect(container.textContent).not.toMatch(/delivered|seen/i);
  });

  it("newestReadPointer returns the larger pointer, the one that is set, or null", () => {
    expect(newestReadPointer(40, 52)).toBe(52);
    expect(newestReadPointer(52, 40)).toBe(52);
    expect(newestReadPointer(null, 52)).toBe(52);
    expect(newestReadPointer(40, undefined)).toBe(40);
    expect(newestReadPointer(null, null)).toBeNull();
    expect(newestReadPointer(undefined, undefined)).toBeNull();
  });
});

/**
 * Phase 3 ticket 100 (spec gap row L10, stories 43 and 44): ↩ on a bubble
 * feeds `quoteFromMessage` into the real Composer's `quoted` prop, which shows
 * "Replying to: <quote>" with ✕ "Cancel reply"; ✕ clears it through
 * `onClearQuoted`, as the Thread wires them.
 */
describe("MessageList reply strip, with the real Composer", () => {
  function ReplyHarness({ messages }: { messages: OFMessage[] }) {
    const [quoted, setQuoted] = useState<QuotedReply | null>(null);
    return (
      <>
        <MessageList {...baseProps} messages={messages} ownerUserId={555}
                     onQuoteReply={(m) => setQuoted(quoteFromMessage(m))} />
        <section aria-label="Composer slot">
          <Composer accountId="acct1" fanId={null} onSend={() => Promise.resolve()}
                    quoted={quoted} onClearQuoted={() => setQuoted(null)} />
        </section>
      </>
    );
  }
  const thread = [msg({ id: 60, text: "see you at <b>nine</b>", fromUser: { id: 42 } })];

  it("clicking ↩ on a bubble shows 'Replying to: <text>' inside the Composer", () => {
    const { getByTitle, getByRole } = renderWithProviders(<ReplyHarness messages={thread} />);
    const composer = within(getByRole("region", { name: "Composer slot" }));
    expect(composer.queryByText(/Replying to/)).toBeNull();
    fireEvent.click(getByTitle("Quote-reply"));
    expect(composer.getByText("Replying to: see you at nine")).toBeTruthy();
    expect(composer.getByRole("button", { name: "Cancel reply" })).toBeTruthy();
  });

  it("✕ 'Cancel reply' removes the strip", () => {
    const { getByTitle, getByRole } = renderWithProviders(<ReplyHarness messages={thread} />);
    const composer = within(getByRole("region", { name: "Composer slot" }));
    fireEvent.click(getByTitle("Quote-reply"));
    fireEvent.click(composer.getByRole("button", { name: "Cancel reply" }));
    expect(composer.queryByText(/Replying to/)).toBeNull();
    expect(composer.queryByRole("button", { name: "Cancel reply" })).toBeNull();
  });
});

/**
 * messages-pro-look-and-feel ticket 143 (Phase 4 spec, Gap rows T1-T3 and T8,
 * stories 1-17): the Bubble action row beside each bubble. The Fan's side has
 * Pin, Reply, Like and Translate; ours has Translate and a "More message
 * actions" menu. Hover or focus shows it from md up, always below md, and a
 * sending, failed or scheduled message has none.
 */
describe("MessageList Bubble action row", () => {
  const handlers = () => ({
    onQuoteReply: vi.fn(), onToggleLike: vi.fn(), onTogglePin: vi.fn(), onUnsend: vi.fn(),
    onSaveAsScript: vi.fn(),
  });
  /** A message's "Message actions" group: in its bubble line, beside the bubble's column. */
  function actionsOf(container: HTMLElement, id: number | string): HTMLElement | null {
    const line = bubbleBox(container, id).parentElement!.parentElement!;
    return within(line).queryByRole("group", { name: "Message actions" });
  }
  const names = (el: HTMLElement, role: "button" | "menuitem") =>
    within(el).getAllByRole(role).map((b) => b.getAttribute("aria-label") ?? b.textContent);
  beforeEach(() => {
    relayPost.mockClear();
  });
  afterEach(() => {
    relayPost.mockImplementation(() => Promise.resolve({}));
  });

  it("an incoming bubble's Message actions are Pin, Reply, Like and Translate, beside its column; set state reads Unpin and Unlike, pressed; each calls its callback with the message", () => {
    const h = handlers();
    const plain = msg({ id: 70, text: "row order", fromUser: { id: 42 } });
    const set = msg({ id: 72, text: "liked and pinned", fromUser: { id: 42 }, isLiked: true, isPinned: true });
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[plain, set]} ownerUserId={555} {...h} />,
    );
    const row = actionsOf(container, 70)!;
    expect(names(row, "button")).toEqual(["Pin", "Reply", "Like", "Translate"]);
    // Beside the bubble's column, not inside it (Gap row T1).
    expect(bubbleBox(container, 70).parentElement!.contains(row)).toBe(false);
    for (const b of within(row).getAllByRole("button")) expect(b.className).toContain(MP.messageList.action);
    const setRow = actionsOf(container, 72)!;
    expect(names(setRow, "button")).toEqual(["Unpin", "Reply", "Unlike", "Translate"]);
    expect(within(setRow).getByRole("button", { name: "Unpin" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(setRow).getByRole("button", { name: "Unlike" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(row).getByRole("button", { name: "Pin" }).getAttribute("aria-pressed")).toBe("false");
    // Glyph colours (criterion 6): idle Like and Pin read the palette's glyph grey, a liked heart its red.
    expect(within(row).getByRole("button", { name: "Like" }).className).toContain("var(--inf-action");
    expect(within(row).getByRole("button", { name: "Pin" }).className).toContain("var(--inf-action");
    expect(within(setRow).getByRole("button", { name: "Unlike" }).className).toContain("var(--inf-liked");
    fireEvent.click(within(row).getByRole("button", { name: "Pin" }));
    fireEvent.click(within(row).getByRole("button", { name: "Reply" }));
    fireEvent.click(within(row).getByRole("button", { name: "Like" }));
    expect(h.onTogglePin).toHaveBeenCalledWith(plain);
    expect(h.onQuoteReply).toHaveBeenCalledWith(plain);
    expect(h.onToggleLike).toHaveBeenCalledWith(plain);
    // Double-click on the bubble still likes (story 10).
    fireEvent.doubleClick(bubbleBox(container, 70));
    expect(h.onToggleLike).toHaveBeenCalledTimes(2);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("a Fan's tip shows no Reward control: its row is Pin, Reply, Like and Translate (Tip reward vetoed by the human 2026-10-15)", () => {
    const h = handlers();
    const tip = msg({ id: 73, text: "a tip for you", fromUser: { id: 42 }, isTip: true });
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[tip]} ownerUserId={555} {...h} />,
    );
    const row = actionsOf(container, 73)!;
    expect(names(row, "button")).toEqual(["Pin", "Reply", "Like", "Translate"]);
    expect(within(row).queryByRole("button", { name: /reward/i })).toBeNull();
    expect(container.querySelector('[title*="reward" i], [aria-label*="reward" i]')).toBeNull();
  });

  it("an outgoing bubble shows Translate and 'More message actions', whose menu holds Reply, Pin, Save as script, Details and Unsend; Escape and an outside pointer-down close it", () => {
    const h = handlers();
    const ours = msg({ id: 71, text: "ours", fromUser: { id: 555 } });
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={[ours]} ownerUserId={555} {...h} />,
    );
    const row = actionsOf(container, 71)!;
    expect(names(row, "button")).toEqual(["Translate", "More message actions"]);
    const more = within(row).getByRole("button", { name: "More message actions" });
    expect(more.getAttribute("aria-haspopup")).toBe("menu");
    expect(more.getAttribute("aria-expanded")).toBe("false");
    for (const [item, cb] of [
      ["Reply", h.onQuoteReply], ["Pin", h.onTogglePin], ["Save as script", h.onSaveAsScript], ["Unsend", h.onUnsend],
    ] as const) {
      fireEvent.click(more);
      expect(more.getAttribute("aria-expanded")).toBe("true");
      const menu = within(row).getByRole("menu");
      expect(names(menu, "menuitem")).toEqual(["Reply", "Pin", "Save as script", "Details", "Unsend"]);
      fireEvent.click(within(menu).getByRole("menuitem", { name: item }));
      expect(cb).toHaveBeenCalledWith(ours);
      expect(within(row).queryByRole("menu")).toBeNull();
    }
    fireEvent.click(more);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(within(row).queryByRole("menu")).toBeNull();
    fireEvent.click(more);
    fireEvent.pointerDown(document.body);
    expect(within(row).queryByRole("menu")).toBeNull();
  });

  it("our pinned bubble's menu reads Unpin; with no handlers the ⋮ holds Details alone", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} onTogglePin={() => {}} messages={[
        msg({ id: 74, text: "ours pinned", fromUser: { id: 555 }, isPinned: true }),
      ]} />,
    );
    const row = actionsOf(container, 74)!;
    fireEvent.click(within(row).getByRole("button", { name: "More message actions" }));
    expect(names(within(row).getByRole("menu"), "menuitem")).toEqual(["Unpin", "Details"]);
    cleanup();
    const bare = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[msg({ id: 75, text: "ours", fromUser: { id: 555 } })]} />,
    );
    const bareRow = actionsOf(bare.container, 75)!;
    expect(names(bareRow, "button")).toEqual(["Translate", "More message actions"]);
    fireEvent.click(within(bareRow).getByRole("button", { name: "More message actions" }));
    expect(names(within(bareRow).getByRole("menu"), "menuitem")).toEqual(["Details"]);
  });

  it("Details (roadmap W4 4.11) swaps the menu for a panel: sent time, who sent it, seen, and the price with its unlock state; Escape closes it", () => {
    const ppv = msg({ id: 77, text: "unlock me", fromUser: { id: 555 }, price: 12.5, isOpened: true });
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[ppv]} lastReadByPeerId={77}
                   attribution={{ "77": { employee_id: 3, display_name: "Kingsley", automation_kind: null,
                                          sender_name: null, color: null } }} />,
    );
    const row = actionsOf(container, 77)!;
    fireEvent.click(within(row).getByRole("button", { name: "More message actions" }));
    fireEvent.click(within(row).getByRole("menuitem", { name: "Details" }));
    expect(within(row).queryByRole("menu")).toBeNull();
    const panel = within(row).getByRole("dialog", { name: "Message details" });
    const facts = Object.fromEntries(Array.from(panel.querySelectorAll("dt"))
      .map((dt) => [dt.textContent, dt.nextElementSibling!.textContent]));
    expect(facts["Sent by"]).toBe("Kingsley");
    expect(facts.Seen).toBe("Seen");
    expect(facts.Price).toBe("$12.50 · unlocked");
    expect(facts.Sent).toMatch(/2026/);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(within(row).queryByRole("dialog")).toBeNull();
  });

  it("a sending, failed or scheduled message has no Message actions, and its status line is unchanged", () => {
    const h = handlers();
    const { container, getByText } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} {...h} onCancelScheduled={() => {}} messages={[
        msg({ id: -1, _tempId: -1, text: "on its way", fromUser: { id: 555 }, _pending: true }),
        msg({ id: -2, _tempId: -2, text: "did not go", fromUser: { id: 555 }, _failed: true }),
        msg({ id: -3, _tempId: -3, text: "later", fromUser: { id: 555 }, _isFutureScheduled: true, _scheduleJobId: 9 }),
      ]} />,
    );
    for (const id of [-1, -2, -3]) expect(actionsOf(container, id)).toBeNull();
    expect(getByText("sending…")).toBeTruthy();
    expect(getByText("failed — retry")).toBeTruthy();
    expect(getByText("cancel")).toBeTruthy();
  });

  it("from md up the row shows on hover or focus inside the bubble line, by opacity only; below md it always shows, and a tap on the bubble changes nothing", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} onQuoteReply={() => {}} messages={[
        msg({ id: 76, text: "hover me", fromUser: { id: 42 } }),
      ]} />,
    );
    const row = actionsOf(container, 76)!;
    const line = bubbleBox(container, 76).parentElement!.parentElement!;
    expect(line.className.split(" ")).toContain("group");
    const before = row.className;
    for (const c of ["md:opacity-0", "md:group-hover:opacity-100", "md:group-focus-within:opacity-100", MP.messageList.actionsIn]) {
      expect(before).toContain(c);
    }
    expect(before).not.toMatch(/(^|\s)(max-md:)?(opacity-0|hidden|pointer-events-none)(\s|$)/);
    expect(before).not.toMatch(/md:hidden|md:pointer-events-none/);
    fireEvent.click(bubbleBox(container, 76));
    expect(row.className).toBe(before);
  });

  it("Translate POSTs that message's stripped text, shows the translation, and a second click shows the original", async () => {
    relayPost.mockImplementation((path: string) => Promise.resolve(path === "/admin/translate"
      ? { results: [{ text: "good morning, love", lang: "es" }] } : {}));
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[
        msg({ id: 77, text: "buenos días, <b>amor</b>", fromUser: { id: 42 } }),
        msg({ id: 78, text: "another one", fromUser: { id: 42 } }),
      ]} />,
    );
    const row = actionsOf(container, 77)!;
    const translate = within(row).getByRole("button", { name: "Translate" });
    expect(translate.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(translate);
    await waitFor(() => expect(bubbleBox(container, 77).textContent).toContain("good morning, love"));
    expect(relayPost).toHaveBeenCalledTimes(1);
    expect(relayPost).toHaveBeenCalledWith("/admin/translate", { texts: ["buenos días, amor"], target: "en" }, { accountId: "acct1" });
    expect(bubbleBox(container, 78).textContent).toContain("another one");
    const shown = within(row).getByRole("button", { name: "Show original" });
    expect(shown.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(shown);
    expect(bubbleBox(container, 77).textContent).toContain("buenos días, amor");
    expect(bubbleBox(container, 77).textContent).not.toContain("good morning, love");
    expect(within(row).getByRole("button", { name: "Translate" })).toBeTruthy();
    // Translated once: a third click is answered from the cache.
    fireEvent.click(within(row).getByRole("button", { name: "Translate" }));
    expect(bubbleBox(container, 77).textContent).toContain("good morning, love");
    expect(relayPost).toHaveBeenCalledTimes(1);
  });

  it("a failed translation keeps the original, titled 'No translation available'; a media-only message has no Translate", async () => {
    relayPost.mockImplementation(() => Promise.reject(new Error("translate down")));
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} onQuoteReply={() => {}} messages={[
        msg({ id: 79, text: "nicht übersetzbar", fromUser: { id: 42 } }),
        msg({ id: 80, text: "", fromUser: { id: 42 }, media: [{ id: 1, type: "photo", files: { thumb: { url: "https://cdn/p.jpg" } } }] }),
      ]} />,
    );
    const row = actionsOf(container, 79)!;
    fireEvent.click(within(row).getByRole("button", { name: "Translate" }));
    await waitFor(() => expect(within(row).getByTitle("No translation available")).toBeTruthy());
    expect(bubbleBox(container, 79).textContent).toContain("nicht übersetzbar");
    expect(names(actionsOf(container, 80)!, "button")).toEqual(["Reply"]);
  });

  it("with the thread-wide translate mode on, a bubble's toggle reads 'Show original', and turning it off shows that bubble's original", async () => {
    relayPost.mockImplementation((path: string, body?: unknown) => Promise.resolve(path === "/admin/translate"
      ? { results: (body as { texts: string[] }).texts.map((t) => ({ text: `EN ${t}`, lang: "fr" })) } : {}));
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[
        msg({ id: 81, text: "bonjour toi", fromUser: { id: 42 } }),
        msg({ id: 82, text: "salut toi", fromUser: { id: 42 } }),
      ]} />,
    );
    window.localStorage.setItem("chatterly:translate-en", "1");
    act(() => { window.dispatchEvent(new Event("storage")); });
    try {
      await waitFor(() => expect(bubbleBox(container, 81).textContent).toContain("EN bonjour toi"));
      const row = actionsOf(container, 81)!;
      const shown = within(row).getByRole("button", { name: "Show original" });
      expect(shown.getAttribute("aria-pressed")).toBe("true");
      fireEvent.click(shown);
      expect(bubbleBox(container, 81).textContent).not.toContain("EN bonjour toi");
      expect(bubbleBox(container, 82).textContent).toContain("EN salut toi");
      expect(within(row).getByRole("button", { name: "Translate" }).getAttribute("aria-pressed")).toBe("false");
    } finally {
      window.localStorage.removeItem("chatterly:translate-en");
      act(() => { window.dispatchEvent(new Event("storage")); });
    }
  });
});

/**
 * Ticket 144 (Phase 4 spec T4-T7, F5, F6): Infloww's Date dividers, a run's
 * avatar on its last bubble line only, and the Jump chip.
 */
describe("MessageList Date dividers, run avatars and the Jump chip", () => {
  const at = (y: number, mo: number, d: number, h = 12, mi = 0, s = 0) => new Date(y, mo - 1, d, h, mi, s).toISOString();
  const NOW = new Date(2026, 9, 15, 12, 0);
  const line = (c: HTMLElement, id: number) => bubbleBox(c, id).parentElement!.parentElement!;
  const slot = (c: HTMLElement, id: number) => line(c, id).querySelector("[data-msg-avatar]");
  /** Fan, Fan, Fan in one minute, then ours, ours in the next. */
  const RUNS = [101, 102, 103].map((id, i) => msg({ id, text: `fan ${id}`, fromUser: { id: 42 }, createdAt: at(2026, 6, 4, 9, 41, i) }))
    .concat([104, 105].map((id, i) => msg({ id, text: `ours ${id}`, fromUser: { id: 555 }, createdAt: at(2026, 6, 4, 9, 42, i) })));

  it("dateDividerLabel reads 'Today', 'Sep 29' on another day this year (yesterday too) and 'Sep 29, 2025' in another year", () => {
    expect(dateDividerLabel(at(2026, 10, 15, 0, 5), NOW)).toBe("Today");
    expect(dateDividerLabel(at(2026, 9, 29), NOW)).toBe("Sep 29");
    expect(dateDividerLabel(at(2026, 10, 14, 23, 59), NOW)).toBe("Oct 14");
    expect(dateDividerLabel(at(2025, 9, 29), NOW)).toBe("Sep 29, 2025");
  });

  it("a separator sits above each day's first message, named 'Sep 29' and 'Today', with no uppercase class", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    try {
      const { container, getAllByRole } = renderWithProviders(
        <MessageList {...baseProps} ownerUserId={555} messages={[
          msg({ id: 90, text: "earlier", createdAt: at(2026, 9, 29, 1, 42) }),
          msg({ id: 91, text: "same day", createdAt: at(2026, 9, 29, 17, 8) }),
          msg({ id: 92, text: "now", createdAt: at(2026, 10, 15, 10, 3) }),
        ]} />,
      );
      const seps = getAllByRole("separator");
      expect(seps.map((s) => [s.getAttribute("aria-label"), s.textContent])).toEqual([["Sep 29", "Sep 29"], ["Today", "Today"]]);
      expect(seps[0].nextElementSibling).toBe(line(container, 90));
      expect(seps[1].nextElementSibling).toBe(line(container, 92));
      for (const s of seps) {
        expect([s, ...s.querySelectorAll("*")].filter((e) => e.classList.contains("uppercase"))).toEqual([]);
        expect(s.className).toContain(MP.messageList.divider);
        expect(s.querySelector("span")!.className).toContain(MP.messageList.dividerLabel);
        expect(s.querySelector("span")!.className).toContain("text-fg-dim");
        expect(s.firstElementChild!.className).toContain("bg-[var(--inf-date-rule,");
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it("messageRuns groups one side, day, minute, Sent by and receipt; pending, failed and future-scheduled stand alone", () => {
    const ours = (id: number, s: number, over: Partial<SeedMsg> = {}) =>
      msg({ id, fromUser: { id: 555 }, createdAt: at(2026, 10, 15, 9, 42, s), ...over });
    const messages = [
      msg({ id: 1, fromUser: { id: 42 }, createdAt: at(2026, 10, 15, 9, 41, 0) }),
      msg({ id: 2, fromUser: { id: 42 }, createdAt: at(2026, 10, 15, 9, 41, 50) }),
      msg({ id: 3, fromUser: { id: 42 }, createdAt: at(2026, 10, 15, 9, 42, 0) }),
      ours(4, 1), ours(5, 2), ours(6, 3), ours(7, 4),
      ours(8, 5, { _pending: true }), ours(9, 6), ours(10, 7, { _failed: true }), ours(11, 8, { _isFutureScheduled: true }),
      msg({ id: 12, fromUser: { id: 42 }, createdAt: at(2026, 10, 16, 9, 42, 0) }),
      msg({ id: 13, fromUser: { id: 42 }, createdAt: at(2026, 10, 17, 9, 42, 0) }), // the day alone splits 12 | 13
    ];
    const label = (sentBy: string | null, receipt: "delivered" | "seen" | null) => ({ sentBy, receipt });
    const labels = [label(null, null), label(null, null), label(null, null),
      label("Sam", "delivered"), label("Sam", "delivered"), label("Kai", "delivered"), label("Kai", "seen"),
      label("Sam", null), label("Sam", "delivered"), label("Sam", null), label("Sam", null), label(null, null), label(null, null)];
    expect(messageRuns(messages, 555, labels).map((r) => r.map((m) => m.id)))
      .toEqual([[1, 2], [3], [4, 5], [6], [7], [8], [9], [10], [11], [12], [13]]);
  });

  it("a Date divider breaks a run: the Fan's lines at 9:41 on two days each hold the avatar, the separator between them", () => {
    const { container, getAllByRole } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[130, 131].map((id, i) =>
        msg({ id, text: `fan ${id}`, fromUser: { id: 42 }, createdAt: at(2026, 9, 28 + i, 9, 41) }))} />,
    );
    expect([130, 131].map((id) => slot(container, id)?.getAttribute("data-msg-avatar") ?? null)).toEqual(["fan", "fan"]);
    const seps = getAllByRole("separator");
    expect(seps).toHaveLength(2);
    expect(seps[1].previousElementSibling).toBe(line(container, 130));
    expect(seps[1].nextElementSibling).toBe(line(container, 131));
  });

  it("only a run's last bubble line holds its avatar, the Fan's first and ours last, each with its URL; earlier lines keep a spacer", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={RUNS}
                   fanAvatar="https://cdn.test/fan.jpg" creatorAvatar="https://cdn.test/me.jpg" />,
    );
    expect([101, 102, 103, 104, 105].map((id) => slot(container, id)?.getAttribute("data-msg-avatar") ?? null))
      .toEqual([null, null, "fan", null, "creator"]);
    expect(line(container, 103).firstElementChild).toBe(slot(container, 103));
    expect(line(container, 105).lastElementChild).toBe(slot(container, 105));
    expect(slot(container, 103)!.querySelector("img")!.getAttribute("src")).toBe("https://cdn.test/fan.jpg");
    expect(slot(container, 105)!.querySelector("img")!.getAttribute("src")).toBe("https://cdn.test/me.jpg");
    for (const id of [103, 105]) expect(slot(container, id)!.className).toContain(MP.messageList.avatar);
    expect(slot(container, 103)!.className).toContain(MP.messageList.avatarIn);
    expect(slot(container, 105)!.className).toContain(MP.messageList.avatarOut);
    for (const [id, edge] of [[101, "firstElementChild"], [104, "lastElementChild"]] as const) {
      const spacer = line(container, id)[edge] as HTMLElement;
      expect(spacer.getAttribute("aria-hidden")).toBe("true");
      expect(spacer.className).toContain(MP.messageList.avatar);
    }
  });

  it("with null URLs the plain circle and the person glyph render and no img does; the relay request list is the same with and without URLs", async () => {
    // Our photo asks for the Fan's vault history, so the list is not empty.
    const media = msg({ id: 106, fromUser: { id: 555 }, createdAt: at(2026, 6, 4, 9, 50),
                        media: [{ id: 1, type: "photo", files: { thumb: { url: "https://cdn.test/p.jpg" } } }] });
    const requests = () => [...relayGet.mock.calls.map((c) => ["GET", c[0]]), ...relayPost.mock.calls.map((c) => ["POST", c[0], c[1]])];
    const renderOnce = async (fanAvatar: string | null, creatorAvatar: string | null) => {
      relayGet.mockClear();
      relayPost.mockClear();
      const r = renderWithProviders(<MessageList {...baseProps} ownerUserId={555} fanId={1001 as FanId} messages={[...RUNS, media]}
                                                 fanAvatar={fanAvatar} creatorAvatar={creatorAvatar} />);
      await act(async () => { await new Promise((ok) => setTimeout(ok, 20)); });
      return { r, calls: requests() };
    };
    const without = await renderOnce(null, null);
    const c = without.r.container;
    expect(c.querySelectorAll("[data-msg-avatar] img")).toHaveLength(0);
    expect(slot(c, 103)!.className).toContain("bg-[var(--inf-fan-avatar,");
    expect(slot(c, 105)!.className).toContain("bg-[var(--inf-creator-avatar,");
    expect(slot(c, 105)!.querySelector("svg")).toBeTruthy();
    cleanup();
    const withUrls = await renderOnce("https://cdn.test/fan.jpg", "https://cdn.test/me.jpg");
    expect(withUrls.r.container.querySelectorAll("[data-msg-avatar] img")).toHaveLength(3);
    expect(without.calls.length).toBeGreaterThan(0);
    expect(withUrls.calls).toEqual(without.calls);
  });

  it("'↓ Jumping to latest…' wears the chip's Geometry and colour pair and never takes a click", () => {
    expect(MP.ours.MessageList.autoPin).toContain("px-3.75 py-1.75 rounded-2xl text-[13px] font-medium");
    const { getByText } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={[msg({ id: 120, text: "hi" })]} />,
    );
    const chip = getByText("↓ Jumping to latest…");
    for (const c of [MP.ours.MessageList.autoPin, "pointer-events-none", "bg-[var(--inf-chip,", "text-[var(--inf-chip-text,"]) {
      expect(chip.className).toContain(c);
    }
    expect(chip.getAttribute("title")).toBeNull();
  });
});

/**
 * Roadmap W4 4.11: a "Message withdrawn" line where one of OUR unsent bubbles
 * stood, from the `unsent_at` our DB stamped (read off the attribution map).
 */
describe("MessageList withdrawn-message lines", () => {
  const entry = (unsent_reason: string | null, unsent_at: string | null = "2026-06-04T12:05:00",
                 created_at: string | null = "2026-06-04T12:01:00") => ({
    employee_id: null, display_name: null, automation_kind: null, sender_name: null, color: null,
    unsent_at, unsent_reason, created_at,
  });

  it("draws each unsend we made in id order, before the first newer message; an automation's reads 'automatically'", () => {
    const messages = [
      msg({ id: 100, text: "first", fromUser: { id: 42 } }),
      msg({ id: 103, text: "after", fromUser: { id: 42 } }),
    ];
    const attribution = {
      "101": entry("manual:chat"),
      "104": entry("automation:unsend_messages"),
      "102": entry(null, null), // never unsent: no line
    };
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={messages} attribution={attribution} />,
    );
    const order = Array.from(container.querySelectorAll("[data-msg-id], [data-withdrawn-id]"))
      .map((el) => el.getAttribute("data-msg-id") ?? `w${el.getAttribute("data-withdrawn-id")}`);
    expect(order).toEqual(["100", "w101", "103", "w104"]);
    const lines = container.querySelectorAll("[data-withdrawn-id]");
    expect(lines[0].textContent).toBe("Message withdrawn");
    expect(lines[1].textContent).toBe("Message withdrawn automatically");
  });

  it("skips a row still on screen and our stand-in ids", () => {
    const messages = [msg({ id: 200 }), msg({ id: 202 })];
    const attribution = {
      "201": entry("manual:chat"),
      "202": entry("manual:chat"),
      "5000000000000001": entry("automation:unsend_messages"),
    };
    expect(withdrawnLines(messages, attribution).map((w) => [w.id, w.before])).toEqual([[201, 1]]);
  });

  it("a line sits under its own day: a new day's line opens the divider, and the message after it shares it", () => {
    const messages = [
      msg({ id: 300, text: "day one", fromUser: { id: 42 }, createdAt: "2026-06-03T12:00:00.000Z" }),
      msg({ id: 303, text: "day two", fromUser: { id: 42 }, createdAt: "2026-06-04T12:10:00.000Z" }),
      msg({ id: 304, text: "day two again", fromUser: { id: 42 }, createdAt: "2026-06-04T12:20:00.000Z" }),
    ];
    const attribution = {
      "301": entry("manual:chat", "2026-06-03T13:00:00", "2026-06-03T12:30:00"),
      "302": entry("manual:chat", "2026-06-04T12:06:00", "2026-06-04T12:05:00"),
      "305": entry("manual:chat", "2026-06-05T12:06:00", "2026-06-05T12:05:00"),
    };
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={messages} attribution={attribution} />,
    );
    const now = new Date();
    const day = (iso: string) => `[${dateDividerLabel(iso, now)}]`;
    const walk = Array.from(container.querySelectorAll("[data-msg-id], [data-withdrawn-id], [role=separator]"))
      .map((el) => el.getAttribute("data-msg-id") ?? (el.hasAttribute("data-withdrawn-id")
        ? `w${el.getAttribute("data-withdrawn-id")}` : `[${el.textContent}]`));
    expect(walk).toEqual([
      day("2026-06-03T12:00:00.000Z"), "300", "w301",
      day("2026-06-04T12:05:00.000Z"), "w302", "303", "304",
      day("2026-06-05T12:05:00.000Z"), "w305",
    ]);
  });

  it("reads the server's zone-less created_at as UTC: near midnight in UTC+2 the line lands on the next local day", () => {
    vi.stubEnv("TZ", "Europe/Berlin"); // CEST, UTC+2 in June
    try {
      const messages = [
        msg({ id: 400, text: "late", fromUser: { id: 42 }, createdAt: "2026-06-04T21:30:00.000Z" }), // 23:30 Jun 4
        msg({ id: 402, text: "after midnight", fromUser: { id: 42 }, createdAt: "2026-06-04T22:40:00.000Z" }), // 00:40 Jun 5
      ];
      // 22:30 UTC = 00:30 Jun 5 in Berlin; read as local time it would stay on Jun 4.
      const attribution = { "401": entry("manual:chat", "2026-06-04T22:35:00", "2026-06-04T22:30:00") };
      const { container } = renderWithProviders(
        <MessageList {...baseProps} ownerUserId={555} messages={messages} attribution={attribution} />,
      );
      const now = new Date();
      const walk = Array.from(container.querySelectorAll("[data-msg-id], [data-withdrawn-id], [role=separator]"))
        .map((el) => el.getAttribute("data-msg-id") ?? (el.hasAttribute("data-withdrawn-id")
          ? `w${el.getAttribute("data-withdrawn-id")}` : `[${el.textContent}]`));
      expect(walk).toEqual([
        `[${dateDividerLabel("2026-06-04T21:30:00.000Z", now)}]`, "400",
        `[${dateDividerLabel("2026-06-04T22:30:00.000Z", now)}]`, "w401", "402",
      ]);
      expect(dateDividerLabel("2026-06-04T21:30:00.000Z", now))
        .not.toBe(dateDividerLabel("2026-06-04T22:30:00.000Z", now));
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
